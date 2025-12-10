import streamlit as st
import sqlite3
import pandas as pd
import datetime
import json

# ==========================================
# 1. 데이터베이스(DB) 세팅 및 함수
# ==========================================
def init_db():
    conn = sqlite3.connect('exam_db.sqlite')
    c = conn.cursor()
    # 학생 테이블
    c.execute('''CREATE TABLE IF NOT EXISTS students
                 (phone TEXT PRIMARY KEY, name TEXT, school TEXT, grade TEXT, last_part INTEGER)''')
    # 답안 테이블 (학생폰번호, 파트, 문항번호, 답안, 확신도)
    c.execute('''CREATE TABLE IF NOT EXISTS answers
                 (phone TEXT, part INTEGER, q_num INTEGER, answer TEXT, confidence TEXT,
                 PRIMARY KEY (phone, part, q_num))''')
    conn.commit()
    conn.close()

def get_student(name, phone):
    conn = sqlite3.connect('exam_db.sqlite')
    c = conn.cursor()
    c.execute("SELECT * FROM students WHERE name=? AND phone=?", (name, phone))
    data = c.fetchone()
    conn.close()
    return data

def save_student(name, phone, school, grade):
    conn = sqlite3.connect('exam_db.sqlite')
    c = conn.cursor()
    # 이미 있으면 업데이트, 없으면 생성 (INSERT OR REPLACE)
    c.execute("INSERT OR REPLACE INTO students (phone, name, school, grade, last_part) VALUES (?, ?, ?, ?, COALESCE((SELECT last_part FROM students WHERE phone=?), 1))", 
              (phone, name, school, grade, phone))
    conn.commit()
    conn.close()

def save_answers(phone, part, answers_dict, conf_dict):
    conn = sqlite3.connect('exam_db.sqlite')
    c = conn.cursor()
    for q_num, ans in answers_dict.items():
        conf = conf_dict.get(q_num, "모름")
        c.execute("INSERT OR REPLACE INTO answers VALUES (?, ?, ?, ?, ?)", 
                  (phone, part, q_num, ans, conf))
    
    # 진행 상황 업데이트 (다음 파트로 넘어감)
    next_part = part + 1
    c.execute("UPDATE students SET last_part = ? WHERE phone = ?", (next_part, phone))
    conn.commit()
    conn.close()

def load_answers(phone):
    conn = sqlite3.connect('exam_db.sqlite')
    df = pd.read_sql_query("SELECT * FROM answers WHERE phone = ?", conn, params=(phone,))
    conn.close()
    return df

# ==========================================
# 2. 정답지 및 채점 로직 (가상 데이터)
# ==========================================
# 실제로는 원장님이 만든 정답표를 여기에 넣습니다.
ANSWER_KEY = {
    1: {1: "2", 2: "1", 3: "3"}, # Part 1 정답 예시
    2: {1: "5", 2: "2"},         # Part 2 정답 예시
    # ... Part 3~7 생략 ...
    8: {} # Part 8은 서술형이므로 AI 채점
}

def ai_grading_mock(question_num, student_answer):
    """
    실제로는 여기서 OpenAI/Gemini API를 호출합니다.
    지금은 테스트를 위해 무조건 정답 처리하거나 특정 키워드 체크만 합니다.
    """
    # [AI 채점 시뮬레이션]
    if len(student_answer) > 5: # 5글자 이상 쓰면 정답으로 간주 (테스트용)
        return True, "논리적 흐름이 우수함"
    else:
        return False, "조건 충족 미흡"

# ==========================================
# 3. 화면 구성 (UI)
# ==========================================
st.set_page_config(page_title="메타인지 진단고사", layout="wide")
init_db()

# 세션 상태 초기화
if 'user_phone' not in st.session_state:
    st.session_state['user_phone'] = None
if 'user_name' not in st.session_state:
    st.session_state['user_name'] = None
if 'current_part' not in st.session_state:
    st.session_state['current_part'] = 1

# --- [화면 1] 로그인 페이지 ---
if st.session_state['user_phone'] is None:
    st.title("🎓 영어 역량 정밀 진단고사")
    st.markdown("### 본인 확인 및 로그인")
    
    with st.form("login_form"):
        name = st.text_input("이름")
        phone = st.text_input("전화번호 (010-0000-0000)")
        
        # 학교 선택 로직
        school_option = st.radio("학교를 선택하세요", ["신원고등학교", "동산고등학교", "직접 입력"])
        custom_school = st.text_input("학교명 직접 입력") if school_option == "직접 입력" else ""
        
        # 학년 선택
        st.markdown("**학년 (2026년 기준)**")
        grade = st.selectbox("학년 선택", ["중3", "고1", "고2", "고3"])
        
        submit = st.form_submit_button("진단 시작하기")
        
        if submit:
            if name and phone:
                final_school = custom_school if school_option == "직접 입력" else school_option
                
                # DB 확인 및 저장
                existing_user = get_student(name, phone)
                save_student(name, phone, final_school, grade)
                
                st.session_state['user_name'] = name
                st.session_state['user_phone'] = phone
                
                # 이어하기 기능: DB에 저장된 마지막 파트 불러오기
                if existing_user:
                    st.session_state['current_part'] = existing_user[4] # last_part column
                    st.success(f"반갑습니다 {name}님! {st.session_state['current_part']}부터 이어서 진행합니다.")
                else:
                    st.session_state['current_part'] = 1
                
                st.rerun()
            else:
                st.error("이름과 전화번호를 정확히 입력해주세요.")

# --- [화면 2] 시험 진행 페이지 (Part 1~8) ---
elif st.session_state['current_part'] <= 8:
    part = st.session_state['current_part']
    st.title(f"📝 Part {part} 진행 중")
    st.markdown(f"**{st.session_state['user_name']}** 학생 | 현재 단계: {part} / 8")
    st.progress(part / 8)

    # 파트별 문항 수 설정 (예시로 Part 1은 3문제라고 가정)
    # 실제로는 파트별 문항수에 맞춰 range 조절 필요
    num_questions = 3 if part < 8 else 2 # Part 8은 2문제 가정
    
    with st.form(f"part_{part}_form"):
        answers = {}
        confidences = {}
        
        st.info("문제를 보고 정답과 본인의 확신도를 체크해주세요.")
        
        for i in range(1, num_questions + 1):
            st.markdown(f"--- \n **문항 {i}**")
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                # Part 8은 서술형(Text), 나머지는 객관식(Select)
                if part == 8:
                    answers[i] = st.text_area(f"Q{i} 정답 입력", key=f"ans_{part}_{i}")
                else:
                    answers[i] = st.selectbox(f"Q{i} 정답 선택", ["선택안함", "1", "2", "3", "4", "5"], key=f"ans_{part}_{i}")
            
            with col2:
                confidences[i] = st.radio(f"Q{i} 확신도", ["확신", "애매", "모름"], horizontal=True, key=f"conf_{part}_{i}")

        submit_part = st.form_submit_button(f"Part {part} 제출 및 다음 단계로")
        
        if submit_part:
            # DB 저장
            save_answers(st.session_state['user_phone'], part, answers, confidences)
            
            # 세션 업데이트
            st.session_state['current_part'] += 1
            st.rerun()

# --- [화면 3] 최종 분석 리포트 ---
else:
    st.title("📊 진단고사 종합 분석 리포트")
    st.success("모든 진단이 완료되었습니다. 결과를 분석 중입니다...")
    
    # DB에서 전체 답안 가져오기
    df = load_answers(st.session_state['user_phone'])
    
    # 분석 로직 (간소화된 버전)
    # 실제로는 여기서 4분면 분석 로직이 돌아갑니다.
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("1. 파트별 분석 (Radar Chart)")
        # 차트 예시 데이터
        chart_data = pd.DataFrame({
            'Part': ['어휘', '어법', '구문', '문해력', '논리', '구조', '전략', '서술형'],
            'Score': [80, 60, 90, 40, 70, 50, 85, 30] # 실제 채점 결과로 대체될 부분
        })
        st.bar_chart(chart_data.set_index('Part'))
        
    with col2:
        st.subheader("2. 메타인지 상태 (4분면)")
        st.markdown("""
        - **견고한 실력 (알고 맞힘):** 45%
        - **불안한 득점 (찍어서 맞힘):** 20% ⚠️
        - **위험한 착각 (틀렸는데 확신):** 15% 🚨
        - **학습 부족 (모르고 틀림):** 20%
        """)
    
    st.divider()
    
    st.subheader("3. 총평 및 처방")
    st.markdown("""
    **[현재 수준]**
    - 어휘력은 우수하나, **문해력(Part 4)과 서술형(Part 8)**에서 큰 약점을 보입니다.
    
    **[우선 순위]**
    1. **Part 4 (문해력):** 한국어 지문 요약 훈련이 시급합니다.
    2. **Part 8 (서술형):** 조건부 영작의 감점 요인을 파악해야 합니다.
    
    **[종합 의견]**
    김철수 학생은 '감'으로 푸는 습관이 있습니다(불안한 득점 20%). 
    신원고 내신 대비를 위해서는 정확한 근거를 찾는 **논리 독해 클리닉** 수강을 권장합니다.
    """)
    
    if st.button("처음으로 돌아가기"):
        st.session_state.clear()
        st.rerun()
