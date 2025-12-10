import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime

# ==========================================
# 1. 구글 시트 연결 설정 (Secrets 활용)
# ==========================================
# Streamlit Cloud에 배포할 때는 'Secrets'에 정보를 넣어야 작동합니다.
def get_db_connection():
    # 권한 설정
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # Secrets에서 정보 가져오기
    # 로컬 테스트 시에는 .streamlit/secrets.toml 파일이 필요하고,
    # 배포 시에는 Streamlit Cloud 대시보드에서 입력합니다.
    credentials_info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(credentials_info, scopes=scope)
    client = gspread.authorize(creds)
    
    # 스프레드시트 열기 (제목으로 찾기)
    sh = client.open("english_exam_db")
    return sh

# ==========================================
# 2. DB 함수 (구글 시트용으로 변경됨)
# ==========================================
def get_student(name, phone):
    try:
        sh = get_db_connection()
        ws = sh.worksheet("students")
        # 모든 데이터 가져와서 Pandas DF로 변환
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        
        # 폰번호는 문자열로 처리 (010...)
        df['phone'] = df['phone'].astype(str)
        
        # 검색
        student = df[(df['name'] == name) & (df['phone'] == phone)]
        
        if not student.empty:
            return student.iloc[0].to_dict()
        return None
    except Exception as e:
        return None

def save_student(name, phone, school, grade):
    sh = get_db_connection()
    ws = sh.worksheet("students")
    
    # 이미 있는지 확인
    cell = ws.find(phone)
    
    if cell:
        # 이미 있으면 정보 업데이트 (행 번호: cell.row)
        # 1:phone, 2:name, 3:school, 4:grade, 5:last_part
        # 기존 last_part 유지 또는 업데이트 로직 필요하나, 여기서는 가입정보만 갱신
        ws.update_cell(cell.row, 2, name)
        ws.update_cell(cell.row, 3, school)
        ws.update_cell(cell.row, 4, grade)
    else:
        # 없으면 새로 추가 (기본 last_part = 1)
        ws.append_row([str(phone), name, school, grade, 1])

def update_last_part(phone, next_part):
    sh = get_db_connection()
    ws = sh.worksheet("students")
    cell = ws.find(str(phone))
    if cell:
        # last_part는 5번째 컬럼이라고 가정
        ws.update_cell(cell.row, 5, next_part)

def save_answers(phone, part, answers_dict, conf_dict):
    sh = get_db_connection()
    ws = sh.worksheet("answers")
    
    # 한 번에 여러 행 추가 (속도 향상)
    rows_to_add = []
    for q_num, ans in answers_dict.items():
        conf = conf_dict.get(q_num, "모름")
        # phone, part, q_num, answer, confidence
        rows_to_add.append([str(phone), part, q_num, ans, conf])
    
    ws.append_rows(rows_to_add)
    
    # 학생 상태 업데이트 (다음 파트로)
    update_last_part(phone, part + 1)

def load_answers(phone):
    sh = get_db_connection()
    ws = sh.worksheet("answers")
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    df['phone'] = df['phone'].astype(str)
    
    # 내 답안만 필터링
    my_answers = df[df['phone'] == str(phone)]
    return my_answers

# ==========================================
# 3. 정답지 및 AI 채점 (가상)
# ==========================================
# 객관식 정답지 예시 (원장님이 채워넣으셔야 합니다)
ANSWER_KEY = {
    1: {1: "2", 2: "1", 3: "3"}, 
    2: {1: "5", 2: "2"},
    # ... 계속 추가 ...
}

def ai_grading_mock(question_num, student_answer):
    # 실제 AI 연동 전 테스트용
    if len(student_answer) > 5:
        return True
    return False

# ==========================================
# 4. 화면 구성 (UI) - 기존과 동일
# ==========================================
st.set_page_config(page_title="메타인지 진단고사", layout="wide")

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
        
        school_option = st.radio("학교를 선택하세요", ["신원고등학교", "동산고등학교", "직접 입력"])
        custom_school = st.text_input("학교명 직접 입력") if school_option == "직접 입력" else ""
        
        st.markdown("**학년 (2026년 기준)**")
        grade = st.selectbox("학년 선택", ["중3", "고1", "고2", "고3"])
        
        submit = st.form_submit_button("진단 시작하기")
        
        if submit:
            if name and phone:
                final_school = custom_school if school_option == "직접 입력" else school_option
                
                with st.spinner("로그인 중..."):
                    existing_user = get_student(name, phone)
                    
                    if existing_user:
                        st.session_state['current_part'] = existing_user['last_part']
                        # 이미 완료한 학생 처리
                        if existing_user['last_part'] > 8:
                            st.session_state['current_part'] = 9
                        else:
                            save_student(name, phone, final_school, grade) # 정보 갱신
                    else:
                        save_student(name, phone, final_school, grade)
                        st.session_state['current_part'] = 1
                    
                    st.session_state['user_name'] = name
                    st.session_state['user_phone'] = phone
                
                st.rerun()
            else:
                st.error("이름과 전화번호를 정확히 입력해주세요.")

# --- [화면 2] 시험 진행 페이지 ---
elif st.session_state['current_part'] <= 8:
    part = st.session_state['current_part']
    st.title(f"📝 Part {part} 진행 중")
    st.markdown(f"**{st.session_state['user_name']}** 학생 | 현재 단계: {part} / 8")
    st.progress(part / 8)

    num_questions = 3 if part < 8 else 2 
    
    with st.form(f"part_{part}_form"):
        answers = {}
        confidences = {}
        st.info("문제를 보고 정답과 본인의 확신도를 체크해주세요.")
        
        for i in range(1, num_questions + 1):
            st.markdown(f"--- \n **문항 {i}**")
            col1, col2 = st.columns([2, 1])
            with col1:
                if part == 8:
                    answers[i] = st.text_area(f"Q{i} 정답 입력", key=f"ans_{part}_{i}")
                else:
                    answers[i] = st.selectbox(f"Q{i} 정답 선택", ["선택안함", "1", "2", "3", "4", "5"], key=f"ans_{part}_{i}")
            with col2:
                confidences[i] = st.radio(f"Q{i} 확신도", ["확신", "애매", "모름"], horizontal=True, key=f"conf_{part}_{i}")

        submit_part = st.form_submit_button(f"Part {part} 제출 및 다음 단계로")
        
        if submit_part:
            with st.spinner("답안 저장 중..."):
                save_answers(st.session_state['user_phone'], part, answers, confidences)
                st.session_state['current_part'] += 1
            st.rerun()

# --- [화면 3] 결과 페이지 ---
else:
    st.title("📊 진단고사 종합 분석 리포트")
    st.success("수고하셨습니다! 모든 데이터가 안전하게 저장되었습니다.")
    
    if st.button("내 결과 확인하기 (로딩)"):
        df = load_answers(st.session_state['user_phone'])
        st.write("저장된 답안 데이터:", df)
        # 여기에 추후 상세 분석 로직 연결
