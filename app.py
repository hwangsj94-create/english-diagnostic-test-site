import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import time

# ==========================================
# [설정] 파트별 문항 상세 구성 (최종 확정안)
# ==========================================
EXAM_STRUCTURE = {
    1: {"title": "어휘력 (Vocabulary)", "type": "simple_obj", "count": 30},
    2: {"title": "어법 지식 (Grammar)", "type": "part2_special", "count": 10}, 
    3: {"title": "구문 해석력 (Syntax Decoding)", "type": "part3_special", "count": 5}, 
    4: {"title": "문해력 (Literacy)", "type": "part4_special", "count": 5}, 
    5: {"title": "문장 연계 (Logical Connectivity)", "type": "part5_special", "count": 5}, 
    6: {"title": "지문 이해 (Macro-Reading)", "type": "part6_sets", "count": 3}, # 3세트
    7: {"title": "문제 풀이 (Strategy)", "type": "simple_obj", "count": 4},
    8: {"title": "서술형 영작 (Writing)", "type": "simple_subj", "count": 5}
}

# ==========================================
# 1. 구글 시트 연결 (Secrets 활용)
# ==========================================
def get_db_connection():
    # Streamlit Cloud 배포 시 secrets에서 정보 로드
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    credentials_info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(credentials_info, scopes=scope)
    client = gspread.authorize(creds)
    return client.open("english_exam_db")

# ==========================================
# 2. DB 함수 (데이터 저장/로딩)
# ==========================================
def get_student(name, phone):
    try:
        sh = get_db_connection()
        ws = sh.worksheet("students")
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        # 폰번호 문자열 변환
        df['phone'] = df['phone'].astype(str)
        # 공백 제거 등 전처리
        name = name.strip()
        phone = phone.strip()
        
        student = df[(df['name'] == name) & (df['phone'] == phone)]
        return student.iloc[0].to_dict() if not student.empty else None
    except Exception as e:
        return None

def save_student(name, phone, school, grade):
    sh = get_db_connection()
    ws = sh.worksheet("students")
    name = name.strip()
    phone = phone.strip()
    
    try:
        # 폰번호로 검색
        cell = ws.find(phone)
        # 이미 존재하면 정보 업데이트
        ws.update_cell(cell.row, 2, name)
        ws.update_cell(cell.row, 3, school)
        ws.update_cell(cell.row, 4, grade)
    except:
        # 없으면 신규 등록 (기본 last_part는 1)
        ws.append_row([str(phone), name, school, grade, 1])

def save_answers_bulk(phone, part, data_list):
    """
    data_list = [{'q_id': '...', 'ans': '...', 'conf': '...'}, ...]
    한 번에 구글 시트 'answers' 탭에 저장
    """
    sh = get_db_connection()
    ws = sh.worksheet("answers")
    
    # 저장할 행 데이터 생성
    rows = [[str(phone), part, d['q_id'], d['ans'], d['conf']] for d in data_list]
    ws.append_rows(rows)
    
    # students 시트의 last_part 업데이트
    ws_stu = sh.worksheet("students")
    try:
        cell = ws_stu.find(str(phone))
        # Part가 8이면 완료 상태(9)로, 아니면 다음 파트로
        next_val = part + 1
        ws_stu.update_cell(cell.row, 5, next_val)
    except:
        pass

# ==========================================
# 3. 메인 앱 화면 (UI)
# ==========================================
st.set_page_config(page_title="영어 역량 정밀 진단", layout="centered")

# CSS: 라디오 버튼 및 입력창 스타일 개선
st.markdown("""
<style>
div.row-widget.stRadio > div {flex-direction: row;} 
div.row-widget.stRadio > div > label {
    background-color: #f8f9fa; padding: 10px 20px; border-radius: 8px; margin-right: 8px; cursor: pointer; border: 1px solid #dee2e6;
}
div.row-widget.stRadio > div > label:hover {background-color: #e9ecef;}
textarea {font-size: 16px !important; line-height: 1.5 !important;}
input[type="text"] {font-size: 16px !important;}
</style>
""", unsafe_allow_html=True)

# 세션 초기화
if 'user_phone' not in st.session_state: st.session_state['user_phone'] = None
if 'user_name' not in st.session_state: st.session_state['user_name'] = None
if 'current_part' not in st.session_state: st.session_state['current_part'] = 1

# ---------------------------------------------------------
# 화면 1: 로그인
# ---------------------------------------------------------
if st.session_state['user_phone'] is None:
    st.title("🎓 영어 역량 정밀 진단고사")
    st.markdown("### OMR 답안 제출 시스템")
    st.info("이름과 전화번호를 정확히 입력해주세요. (이어하기 가능)")
    
    with st.form("login_form"):
        name = st.text_input("이름")
        phone = st.text_input("전화번호 (숫자만 입력, 예: 01012345678)")
        school_opt = st.radio("학교", ["신원고등학교", "동산고등학교", "직접 입력"])
        custom_school = st.text_input("학교명 입력") if school_opt == "직접 입력" else ""
        grade = st.selectbox("학년 (2026년 기준)", ["중3", "고1", "고2", "고3"])
        
        if st.form_submit_button("시험 시작 / 이어하기"):
            if name and phone:
                final_school = custom_school if school_opt == "직접 입력" else school_opt
                
                with st.spinner("학생 정보를 확인 중입니다..."):
                    stu = get_student(name, phone)
                    if stu:
                        # 기존 학생: 진행 단계 불러오기
                        cp = stu['last_part']
                        st.session_state['current_part'] = 9 if cp > 8 else cp
                        # 정보 갱신 (학년 등 변경 가능성)
                        save_student(name, phone, final_school, grade)
                    else:
                        # 신규 학생
                        save_student(name, phone, final_school, grade)
                        st.session_state['current_part'] = 1
                    
                    st.session_state['user_name'] = name
                    st.session_state['user_phone'] = phone
                st.rerun()
            else:
                st.error("이름과 전화번호를 모두 입력해주세요.")

# ---------------------------------------------------------
# 화면 2: 시험 진행 (Part 1 ~ 8)
# ---------------------------------------------------------
elif st.session_state['current_part'] <= 8:
    part = st.session_state['current_part']
    info = EXAM_STRUCTURE[part]
    
    st.title(f"Part {part}. {info['title']}")
    st.progress(part / 8)
    
    with st.form(f"exam_form_{part}"):
        
        # ------------------------------------
        # TYPE 1: 단순 객관식 (Part 1, 7)
        # ------------------------------------
        if info['type'] == 'simple_obj':
            st.info(f"총 {info['count']}문항입니다. 알맞은 정답을 선택하세요.")
            for i in range(1, info['count'] + 1):
                st.markdown(f"**문항 {i}**")
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.radio(f"Q{i} 정답", ["1", "2", "3", "4", "5"], horizontal=True, key=f"p{part}_q{i}", label_visibility="collapsed")
                with c2:
                    st.radio(f"확신도", ["확신", "애매", "모름"], horizontal=False, key=f"p{part}_c{i}", label_visibility="collapsed")
                st.markdown("---")

        # ------------------------------------
        # TYPE 2: Part 2 (1~9 객관식, 10 주관식)
        # ------------------------------------
        elif info['type'] == 'part2_special':
            st.info("1~9번은 객관식, 10번은 주관식입니다.")
            
            # 1~9번 (객관식)
            for i in range(1, 10):
                st.markdown(f"**문항 {i}**")
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.radio(f"Q{i} 정답", ["1", "2", "3", "4", "5"], horizontal=True, key=f"p2_q{i}", label_visibility="collapsed")
                with c2:
                    st.radio("확신도", ["확신", "애매", "모름"], key=f"p2_c{i}")
                st.markdown("---")
            
            # 10번 (주관식 2칸)
            st.markdown(f"**문항 10** (틀린 부분을 찾아 고치시오)")
            c1, c2, c3 = st.columns([2, 2, 1])
            with c1: st.text_input("틀린 단어", key="p2_q10_wrong")
            with c2: st.text_input("고친 단어", key="p2_q10_correct")
            with c3: st.radio("확신도", ["확신", "애매", "모름"], key="p2_c10")
            st.markdown("---")

        # ------------------------------------
        # TYPE 3: Part 3 (복합형 5문항)
        # ------------------------------------
        elif info['type'] == 'part3_special':
            st.info("각 문항의 지시사항에 따라 주관식과 객관식 답안을 입력하세요.")
            
            # Q1
            st.markdown("**문항 1** (주어/동사 찾기 + 내용 일치)")
            c1, c2 = st.columns(2)
            with c1: st.text_input("(1) Main Subject", key="p3_q1_subj")
            with c2: st.text_input("(1) Main Verb", key="p3_q1_verb")
            st.markdown("(2) 내용 일치")
            st.radio("Q1 정답", ["1","2","3","4","5"], horizontal=True, key="p3_q1_obj", label_visibility="collapsed")
            st.radio("Q1 확신도", ["확신", "애매", "모름"], horizontal=True, key="p3_c1")
            st.markdown("---")

            # Q2
            st.markdown("**문항 2** (주어/동사 찾기 + 해석 적절성)")
            c1, c2 = st.columns(2)
            with c1: st.text_input("(1) Main Subject", key="p3_q2_subj")
            with c2: st.text_input("(1) Main Verb", key="p3_q2_verb")
            st.markdown("(2) 해석 적절성")
            st.radio("Q2 정답", ["1","2","3","4","5"], horizontal=True, key="p3_q2_obj", label_visibility="collapsed")
            st.radio("Q2 확신도", ["확신", "애매", "모름"], horizontal=True, key="p3_c2")
            st.markdown("---")

            # Q3
            st.markdown("**문항 3** (행위 주체 + 해석)")
            st.text_input("(1) Subject of 'Convinced'", key="p3_q3_subj")
            st.markdown("(2) 올바른 해석")
            st.radio("Q3 정답", ["1","2","3","4","5"], horizontal=True, key="p3_q3_obj", label_visibility="collapsed")
            st.radio("Q3 확신도", ["확신", "애매", "모름"], horizontal=True, key="p3_c3")
            st.markdown("---")

            # Q4
            st.markdown("**문항 4** (주어/동사 찾기 + 구조 분석)")
            c1, c2 = st.columns(2)
            with c1: st.text_input("(1) Main Subject", key="p3_q4_subj")
            with c2: st.text_input("(1) Main Verb", key="p3_q4_verb")
            st.markdown("(2) 구조 분석")
            st.radio("Q4 정답", ["1","2","3","4","5"], horizontal=True, key="p3_q4_obj", label_visibility="collapsed")
            st.radio("Q4 확신도", ["확신", "애매", "모름"], horizontal=True, key="p3_c4")
            st.markdown("---")

            # Q5
            st.markdown("**문항 5** (시사하는 바 + 빈칸 채우기)")
            st.markdown("(1) 시사하는 바")
            st.radio("Q5 정답", ["1","2","3","4","5"], horizontal=True, key="p3_q5_obj", label_visibility="collapsed")
            st.text_input("(2) 빈칸 채우기", key="p3_q5_text")
            st.radio("Q5 확신도", ["확신", "애매", "모름"], horizontal=True, key="p3_c5")
            st.markdown("---")

        # ------------------------------------
        # TYPE 4: Part 4 (1,2,5 주관식 / 3,4 객관식)
        # ------------------------------------
        elif info['type'] == 'part4_special':
            st.info("문항별 유형에 맞춰 답안을 작성하세요.")
            for i in range(1, 6):
                st.markdown(f"**문항 {i}**")
                if i in [1, 2, 5]: # 주관식
                    st.text_area(f"Q{i} 답안 작성", key=f"p4_q{i}", height=80)
                else: # 3,4 객관식
                    st.radio(f"Q{i} 정답", ["1","2","3","4","5"], horizontal=True, key=f"p4_q{i}", label_visibility="collapsed")
                
                st.radio(f"Q{i} 확신도", ["확신", "애매", "모름"], horizontal=True, key=f"p4_c{i}")
                st.markdown("---")

        # ------------------------------------
        # TYPE 5: Part 5 (1,2,5 복합 / 3,4 주관식)
        # ------------------------------------
        elif info['type'] == 'part5_special':
            st.info("연결사 추론 및 지시어 파악 문제입니다.")
            
            # Q1, Q2, Q5 (복합)
            for i in [1, 2, 5]:
                st.markdown(f"**문항 {i}**")
                st.markdown("(1) 정답 선택")
                st.radio(f"Q{i}-1", ["1","2","3","4","5"], horizontal=True, key=f"p5_q{i}_obj", label_visibility="collapsed")
                st.text_input("(2) 이유/근거 서술", key=f"p5_q{i}_text")
                st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key=f"p5_c{i}")
                st.markdown("---")
            
            # Q3, Q4 (단독 서술)
            for i in [3, 4]:
                st.markdown(f"**문항 {i}**")
                st.text_input("정답 입력", key=f"p5_q{i}_text")
                st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key=f"p5_c{i}")
                st.markdown("---")

        # ------------------------------------
        # TYPE 6: Part 6 (세트형 3세트)
        # ------------------------------------
        elif info['type'] == 'part6_sets':
            st.info("지문을 읽고 4개의 물음에 답하세요. (확신도는 세트당 1회 체크)")
            
            # 전체 문항 번호 카운터 (1~12)
            q_ids = list(range(1, 13))
            
            # Set 1 (Q1~Q4)
            st.markdown("### [Set 1] 지문")
            st.text_input(f"Q1. [Keyword] 핵심 소재", key=f"p6_q1")
            st.radio(f"Q2. [Tone] 태도", ["1","2","3","4","5"], horizontal=True, key=f"p6_q2")
            st.radio(f"Q3. [Flow] 전개 구조 (4지선다)", ["1","2","3","4"], horizontal=True, key=f"p6_q3")
            st.text_area(f"Q4. [Summary] 요약", key=f"p6_q4", height=80)
            st.radio("Set 1 전체 확신도", ["확신", "애매", "모름"], horizontal=True, key="p6_set1_conf")
            st.markdown("---")
            
            # Set 2 (Q5~Q8)
            st.markdown("### [Set 2] 지문")
            st.text_input(f"Q5. [Keyword] 핵심 소재", key=f"p6_q5")
            st.radio(f"Q6. [Tone] 태도", ["1","2","3","4","5"], horizontal=True, key=f"p6_q6")
            st.radio(f"Q7. [Flow] 전개 구조 (4지선다)", ["1","2","3","4"], horizontal=True, key=f"p6_q7")
            st.text_area(f"Q8. [Summary] 요약", key=f"p6_q8", height=80)
            st.radio("Set 2 전체 확신도", ["확신", "애매", "모름"], horizontal=True, key="p6_set2_conf")
            st.markdown("---")
            
            # Set 3 (Q9~Q12)
            st.markdown("### [Set 3] 지문")
            st.text_input(f"Q9. [Keyword] 핵심 소재", key=f"p6_q9")
            st.radio(f"Q10. [Tone] 태도", ["1","2","3","4","5"], horizontal=True, key=f"p6_q10")
            st.radio(f"Q11. [Flow] 전개 구조 (4지선다)", ["1","2","3","4"], horizontal=True, key=f"p6_q11")
            st.text_area(f"Q12. [Summary] 요약", key=f"p6_q12", height=80)
            st.radio("Set 3 전체 확신도", ["확신", "애매", "모름"], horizontal=True, key="p6_set3_conf")
            st.markdown("---")

        # ------------------------------------
        # TYPE 8: Part 8 (서술형)
        # ------------------------------------
        elif info['type'] == 'simple_subj':
            st.info("조건에 맞춰 정확한 영어 문장을 작성하세요. (철자, 문장부호 주의)")
            for i in range(1, info['count'] + 1):
                st.markdown(f"**문항 {i}**")
                st.text_area(f"Q{i} 영작 답안", height=100, key=f"p{part}_q{i}")
                st.radio(f"Q{i} 확신도", ["확신", "애매", "모름"], horizontal=True, key=f"p{part}_c{i}")
                st.markdown("---")

        # ==========================================
        # [제출 버튼] 및 데이터 수집/저장 로직 (생략 없음!)
        # ==========================================
        if st.form_submit_button(f"Part {part} 제출 및 저장"):
            final_data = []
            
            # --- 1. 단순 객관식/주관식 (Part 1, 7, 8) ---
            if info['type'] in ['simple_obj', 'simple_subj']:
                for i in range(1, info['count'] + 1):
                    final_data.append({
                        'q_id': str(i),
                        'ans': st.session_state.get(f"p{part}_q{i}", ""),
                        'conf': st.session_state.get(f"p{part}_c{i}", "모름")
                    })
            
            # --- 2. Part 2 (혼합) ---
            elif info['type'] == 'part2_special':
                for i in range(1, 10):
                    final_data.append({'q_id': str(i), 'ans': st.session_state.get(f"p2_q{i}", ""), 'conf': st.session_state.get(f"p2_c{i}", "모름")})
                # 10번 (칸 2개)
                final_data.append({'q_id': '10_wrong', 'ans': st.session_state.get("p2_q10_wrong", ""), 'conf': st.session_state.get("p2_c10", "모름")})
                final_data.append({'q_id': '10_correct', 'ans': st.session_state.get("p2_q10_correct", ""), 'conf': st.session_state.get("p2_c10", "모름")})

            # --- 3. Part 3 (복합) ---
            elif info['type'] == 'part3_special':
                # Q1
                final_data.append({'q_id': '1_subj', 'ans': st.session_state.get("p3_q1_subj", ""), 'conf': st.session_state.get("p3_c1", "모름")})
                final_data.append({'q_id': '1_verb', 'ans': st.session_state.get("p3_q1_verb", ""), 'conf': st.session_state.get("p3_c1", "모름")})
                final_data.append({'q_id': '1_obj', 'ans': st.session_state.get("p3_q1_obj", ""), 'conf': st.session_state.get("p3_c1", "모름")})
                # Q2
                final_data.append({'q_id': '2_subj', 'ans': st.session_state.get("p3_q2_subj", ""), 'conf': st.session_state.get("p3_c2", "모름")})
                final_data.append({'q_id': '2_verb', 'ans': st.session_state.get("p3_q2_verb", ""), 'conf': st.session_state.get("p3_c2", "모름")})
                final_data.append({'q_id': '2_obj', 'ans': st.session_state.get("p3_q2_obj", ""), 'conf': st.session_state.get("p3_c2", "모름")})
                # Q3
                final_data.append({'q_id': '3_subj', 'ans': st.session_state.get("p3_q3_subj", ""), 'conf': st.session_state.get("p3_c3", "모름")})
                final_data.append({'q_id': '3_obj', 'ans': st.session_state.get("p3_q3_obj", ""), 'conf': st.session_state.get("p3_c3", "모름")})
                # Q4
                final_data.append({'q_id': '4_subj', 'ans': st.session_state.get("p3_q4_subj", ""), 'conf': st.session_state.get("p3_c4", "모름")})
                final_data.append({'q_id': '4_verb', 'ans': st.session_state.get("p3_q4_verb", ""), 'conf': st.session_state.get("p3_c4", "모름")})
                final_data.append({'q_id': '4_obj', 'ans': st.session_state.get("p3_q4_obj", ""), 'conf': st.session_state.get("p3_c4", "모름")})
                # Q5
                final_data.append({'q_id': '5_obj', 'ans': st.session_state.get("p3_q5_obj", ""), 'conf': st.session_state.get("p3_c5", "모름")})
                final_data.append({'q_id': '5_text', 'ans': st.session_state.get("p3_q5_text", ""), 'conf': st.session_state.get("p3_c5", "모름")})

            # --- 4. Part 4 (혼합) ---
            elif info['type'] == 'part4_special':
                for i in range(1, 6):
                    final_data.append({'q_id': str(i), 'ans': st.session_state.get(f"p4_q{i}", ""), 'conf': st.session_state.get(f"p4_c{i}", "모름")})

            # --- 5. Part 5 (복합) ---
            elif info['type'] == 'part5_special':
                # Q1, 2, 5 (복합)
                for i in [1, 2, 5]:
                    final_data.append({'q_id': f"{i}_obj", 'ans': st.session_state.get(f"p5_q{i}_obj", ""), 'conf': st.session_state.get(f"p5_c{i}", "모름")})
                    final_data.append({'q_id': f"{i}_text", 'ans': st.session_state.get(f"p5_q{i}_text", ""), 'conf': st.session_state.get(f"p5_c{i}", "모름")})
                # Q3, 4 (단독)
                for i in [3, 4]:
                    final_data.append({'q_id': f"{i}_text", 'ans': st.session_state.get(f"p5_q{i}_text", ""), 'conf': st.session_state.get(f"p5_c{i}", "모름")})

            # --- 6. Part 6 (세트형) ---
            elif info['type'] == 'part6_sets':
                # Set 1 (Q1~Q4) - Conf 1
                conf1 = st.session_state.get("p6_set1_conf", "모름")
                for i in range(1, 5):
                    final_data.append({'q_id': str(i), 'ans': st.session_state.get(f"p6_q{i}", ""), 'conf': conf1})
                
                # Set 2 (Q5~Q8) - Conf 2
                conf2 = st.session_state.get("p6_set2_conf", "모름")
                for i in range(5, 9):
                    final_data.append({'q_id': str(i), 'ans': st.session_state.get(f"p6_q{i}", ""), 'conf': conf2})
                
                # Set 3 (Q9~Q12) - Conf 3
                conf3 = st.session_state.get("p6_set3_conf", "모름")
                for i in range(9, 13):
                    final_data.append({'q_id': str(i), 'ans': st.session_state.get(f"p6_q{i}", ""), 'conf': conf3})

            # --- 최종 저장 ---
            with st.spinner("답안을 저장 중입니다..."):
                save_answers_bulk(st.session_state['user_phone'], part, final_data)
                time.sleep(1) # 저장 안정성 확보
                st.session_state['current_part'] += 1
                st.rerun()

# ---------------------------------------------------------
# 화면 3: 완료
# ---------------------------------------------------------
else:
    st.balloons()
    st.title("🎉 진단 완료")
    st.success("수고하셨습니다. 모든 답안이 안전하게 제출되었습니다.")
    st.info("원장님께 결과 리포트를 요청하세요.")
    
    if st.button("처음으로 돌아가기"):
        st.session_state.clear()
        st.rerun()
