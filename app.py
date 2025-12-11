import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.graph_objects as go
import plotly.express as px
import time

# ==========================================
# [설정] 파트별 문항 상세 구성
# ==========================================
EXAM_STRUCTURE = {
    1: {"title": "어휘력 (Vocabulary)", "type": "simple_obj", "count": 30},
    2: {"title": "어법 지식 (Grammar)", "type": "part2_special", "count": 10}, 
    3: {"title": "구문 해석력 (Syntax Decoding)", "type": "part3_special", "count": 5}, 
    4: {"title": "문해력 (Literacy)", "type": "part4_special", "count": 5}, 
    5: {"title": "문장 연계 (Logical Connectivity)", "type": "part5_special", "count": 5}, 
    6: {"title": "지문 이해 (Macro-Reading)", "type": "part6_sets", "count": 3},
    7: {"title": "문제 풀이 (Strategy)", "type": "simple_obj", "count": 4},
    8: {"title": "서술형 영작 (Writing)", "type": "simple_subj", "count": 5}
}

# ==========================================
# 1. DB 및 채점 엔진 연결
# ==========================================
def get_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    credentials_info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(credentials_info, scopes=scope)
    return gspread.authorize(creds)

def get_db_connection():
    client = get_client()
    return client.open("english_exam_db")

@st.cache_data(ttl=600)
def load_answer_key():
    sh = get_db_connection()
    ws = sh.worksheet("answer_key")
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    df['part'] = df['part'].astype(str)
    df['q_id'] = df['q_id'].astype(str)
    return df

# --- [변경] 전화번호 대신 이메일로 검색 ---
def get_student(name, email):
    try:
        sh = get_db_connection()
        ws = sh.worksheet("students")
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        
        # 공백 제거 및 소문자 변환 (이메일은 대소문자 구분 없음)
        name = name.strip()
        email = email.strip().lower() # 이메일 정규화
        
        # 데이터프레임의 email 컬럼도 정규화
        if 'email' in df.columns:
            df['email'] = df['email'].astype(str).str.strip().str.lower()
            df['name'] = df['name'].astype(str).str.strip()
            
            student = df[(df['name'] == name) & (df['email'] == email)]
            return student.iloc[0].to_dict() if not student.empty else None
        else:
            st.error("구글 시트(students)의 A열 제목을 'phone'에서 'email'로 변경해주세요!")
            return None
    except:
        return None

# --- [변경] 이메일로 저장 ---
def save_student(name, email, school, grade):
    sh = get_db_connection()
    ws = sh.worksheet("students")
    name = name.strip()
    email = email.strip().lower()
    
    try:
        # 이메일로 검색
        cell = ws.find(email)
        # 정보 업데이트
        ws.update_cell(cell.row, 2, name)
        ws.update_cell(cell.row, 3, school)
        ws.update_cell(cell.row, 4, grade)
    except:
        # 신규 등록
        ws.append_row([email, name, school, grade, 1])

# --- [변경] 이메일과 함께 답안 저장 ---
def save_answers_bulk(email, part, data_list):
    sh = get_db_connection()
    ws = sh.worksheet("answers")
    
    rows = [[email, part, d['q_id'], d['ans'], d['conf']] for d in data_list]
    ws.append_rows(rows)
    
    ws_stu = sh.worksheet("students")
    try:
        cell = ws_stu.find(email)
        ws_stu.update_cell(cell.row, 5, part + 1)
    except:
        pass

def load_student_answers(email):
    sh = get_db_connection()
    ws = sh.worksheet("answers")
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    # 이메일 정규화 후 검색
    if 'email' in df.columns:
        df['email'] = df['email'].astype(str).str.strip().str.lower()
        return df[df['email'] == str(email).strip().lower()]
    else:
        return pd.DataFrame()

# ==========================================
# 2. 채점 및 분석 로직
# ==========================================
def calculate_results(email):
    student_ans_df = load_student_answers(email)
    key_df = load_answer_key()
    results = []
    
    if student_ans_df.empty:
        return pd.DataFrame()

    for _, row in student_ans_df.iterrows():
        part = str(row['part'])
        q_id = str(row['q_id'])
        user_ans = str(row['answer']).strip()
        conf = row['confidence']
        
        key_row = key_df[(key_df['part'] == part) & (key_df['q_id'] == q_id)]
        
        if key_row.empty: continue
            
        correct_ans = str(key_row.iloc[0]['answer']).strip()
        grading_type = key_row.iloc[0]['grading_type']
        keywords = str(key_row.iloc[0]['keywords'])
        
        is_correct = False
        
        if grading_type == 'exact':
            if user_ans.replace(" ", "").lower() == correct_ans.replace(" ", "").lower():
                is_correct = True
        elif grading_type == 'strict':
            if user_ans.strip() == correct_ans.strip():
                is_correct = True
        elif grading_type == 'ai_match':
            if keywords:
                required_words = [k.strip() for k in keywords.split(',')]
                match_count = sum(1 for w in required_words if w in user_ans)
                if match_count >= len(required_words) * 0.7:
                    is_correct = True
            else:
                if len(user_ans) > 5: is_correct = True
        
        quadrant = ""
        if is_correct:
            quadrant = "Master" if conf == "확신" else "Lucky"
        else:
            quadrant = "Delusion" if conf == "확신" else "Deficiency"
            
        results.append({'part': int(part), 'q_id': q_id, 'is_correct': is_correct, 'quadrant': quadrant})
        
    return pd.DataFrame(results)

def show_report_dashboard(df_results, student_name):
    st.markdown(f"## 📊 {student_name}님의 진단 분석 리포트")
    if df_results.empty:
        st.warning("분석할 데이터가 없습니다.")
        return

    total_q = len(df_results)
    correct_q = len(df_results[df_results['is_correct'] == True])
    score = int((correct_q / total_q) * 100) if total_q > 0 else 0
    
    c1, c2, c3 = st.columns(3)
    c1.metric("총점", f"{score}점")
    c2.metric("맞은 개수", f"{correct_q} / {total_q}")
    grade_pred = "1등급" if score >= 90 else "2~3등급" if score >= 70 else "4등급 이하"
    c3.metric("예상 등급", grade_pred)
    st.divider()
    
    # Radar Chart
    st.subheader("1. 영역별 역량 분석")
    part_stats = df_results.groupby('part')['is_correct'].mean() * 100
    all_parts = pd.Series(0, index=range(1, 9))
    part_stats = part_stats.combine_first(all_parts).sort_index()
    
    df_radar = pd.DataFrame({
        'Part': [EXAM_STRUCTURE[p]['title'].split('(')[0] for p in range(1,9)],
        'Score': part_stats.values
    })
    fig = px.line_polar(df_radar, r='Score', theta='Part', line_close=True)
    fig.update_traces(fill='toself')
    st.plotly_chart(fig, use_container_width=True)
    
    # Quadrant Chart
    st.subheader("2. 메타인지(확신도) 분석")
    quad_counts = df_results['quadrant'].value_counts()
    colors = {'Master': '#28a745', 'Lucky': '#ffc107', 'Delusion': '#dc3545', 'Deficiency': '#6c757d'}
    fig2 = px.pie(names=quad_counts.index, values=quad_counts.values, hole=0.5, color=quad_counts.index, color_discrete_map=colors)
    st.plotly_chart(fig2, use_container_width=True)

# ==========================================
# 4. 메인 앱 실행
# ==========================================
st.set_page_config(page_title="영어 역량 정밀 진단", layout="centered")

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

# 세션 키 변경 (phone -> email)
if 'user_email' not in st.session_state: st.session_state['user_email'] = None
if 'user_name' not in st.session_state: st.session_state['user_name'] = None
if 'current_part' not in st.session_state: st.session_state['current_part'] = 1
if 'view_mode' not in st.session_state: st.session_state['view_mode'] = False

# ---------------------------------------------------------
# 화면 1: 로그인 (이메일 입력으로 변경)
# ---------------------------------------------------------
if st.session_state['user_email'] is None:
    st.title("🎓 영어 역량 정밀 진단고사")
    st.info("로그인 시 이메일 주소를 사용합니다. (예: student@naver.com)")
    
    tab1, tab2 = st.tabs(["시험 응시 / 이어하기", "내 결과 확인하기"])
    
    with tab1:
        with st.form("login_form"):
            name = st.text_input("이름")
            email = st.text_input("이메일 주소")
            school_opt = st.radio("학교", ["신원고등학교", "동산고등학교", "직접 입력"])
            custom_school = st.text_input("학교명 입력") if school_opt == "직접 입력" else ""
            grade = st.selectbox("학년 (2026년 기준)", ["중3", "고1", "고2", "고3"])
            
            if st.form_submit_button("진단 시작하기"):
                if name and email:
                    # 이메일 유효성 체크 (간단히 @ 포함 여부만)
                    if "@" not in email:
                        st.error("올바른 이메일 형식이 아닙니다.")
                    else:
                        final_school = custom_school if school_opt == "직접 입력" else school_opt
                        with st.spinner("정보 확인 중..."):
                            stu = get_student(name, email)
                            if stu:
                                cp = stu['last_part']
                                st.session_state['current_part'] = 9 if cp > 8 else cp
                                save_student(name, email, final_school, grade)
                            else:
                                save_student(name, email, final_school, grade)
                                st.session_state['current_part'] = 1
                            
                            st.session_state['user_name'] = name
                            st.session_state['user_email'] = email
                            st.session_state['view_mode'] = False
                        st.rerun()
                else:
                    st.error("이름과 이메일을 입력하세요.")
                    
    with tab2:
        with st.form("check_result"):
            chk_name = st.text_input("이름")
            chk_email = st.text_input("이메일 주소")
            if st.form_submit_button("결과 조회"):
                if chk_name and chk_email:
                    stu = get_student(chk_name, chk_email)
                    if stu:
                        st.session_state['user_name'] = chk_name
                        st.session_state['user_email'] = chk_email
                        st.session_state['view_mode'] = True
                        st.rerun()
                    else:
                        st.error("응시 이력이 없습니다. (이름/이메일 확인)")
                else:
                    st.warning("이름과 이메일을 입력해주세요.")

# ---------------------------------------------------------
# 화면 2: 시험 진행
# ---------------------------------------------------------
elif not st.session_state['view_mode'] and st.session_state['current_part'] <= 8:
    part = st.session_state['current_part']
    info = EXAM_STRUCTURE[part]
    
    st.title(f"Part {part}. {info['title']}")
    st.progress(part / 8)
    
    with st.form(f"exam_form_{part}"):
        # --- UI 그리기 (기존 코드와 동일) ---
        if info['type'] == 'simple_obj':
            st.info(f"총 {info['count']}문항입니다.")
            for i in range(1, info['count'] + 1):
                st.markdown(f"**문항 {i}**")
                c1, c2 = st.columns([3, 1])
                with c1: st.radio(f"Q{i} 정답", ["1","2","3","4","5"], horizontal=True, key=f"p{part}_q{i}", label_visibility="collapsed")
                with c2: st.radio(f"확신도", ["확신", "애매", "모름"], horizontal=False, key=f"p{part}_c{i}", label_visibility="collapsed")
                st.markdown("---")

        elif info['type'] == 'part2_special':
            for i in range(1, 10):
                st.markdown(f"**문항 {i}**")
                c1, c2 = st.columns([3, 1])
                with c1: st.radio(f"Q{i} 정답", ["1","2","3","4","5"], horizontal=True, key=f"p2_q{i}", label_visibility="collapsed")
                with c2: st.radio("확신도", ["확신", "애매", "모름"], key=f"p2_c{i}")
                st.markdown("---")
            st.markdown(f"**문항 10**")
            c1, c2, c3 = st.columns([2, 2, 1])
            with c1: st.text_input("틀린 단어", key="p2_q10_wrong")
            with c2: st.text_input("고친 단어", key="p2_q10_correct")
            with c3: st.radio("확신도", ["확신", "애매", "모름"], key="p2_c10")

        elif info['type'] == 'part3_special':
            st.markdown("**문항 1**")
            c1, c2 = st.columns(2)
            with c1: st.text_input("(1) Main Subject", key="p3_q1_subj")
            with c2: st.text_input("(1) Main Verb", key="p3_q1_verb")
            st.radio("(2) 정답", ["1","2","3","4","5"], horizontal=True, key="p3_q1_obj")
            st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key="p3_c1")
            st.markdown("---")
            st.markdown("**문항 2**")
            c1, c2 = st.columns(2)
            with c1: st.text_input("(1) Main Subject", key="p3_q2_subj")
            with c2: st.text_input("(1) Main Verb", key="p3_q2_verb")
            st.radio("(2) 정답", ["1","2","3","4","5"], horizontal=True, key="p3_q2_obj")
            st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key="p3_c2")
            st.markdown("---")
            st.markdown("**문항 3**")
            st.text_input("(1) Subject of 'Convinced'", key="p3_q3_subj")
            st.radio("(2) 정답", ["1","2","3","4","5"], horizontal=True, key="p3_q3_obj")
            st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key="p3_c3")
            st.markdown("---")
            st.markdown("**문항 4**")
            c1, c2 = st.columns(2)
            with c1: st.text_input("(1) Main Subject", key="p3_q4_subj")
            with c2: st.text_input("(1) Main Verb", key="p3_q4_verb")
            st.radio("(2) 정답", ["1","2","3","4","5"], horizontal=True, key="p3_q4_obj")
            st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key="p3_c4")
            st.markdown("---")
            st.markdown("**문항 5**")
            st.radio("(1) 정답", ["1","2","3","4","5"], horizontal=True, key="p3_q5_obj")
            st.text_input("(2) 빈칸 채우기", key="p3_q5_text")
            st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key="p3_c5")
            st.markdown("---")

        elif info['type'] == 'part4_special':
            for i in range(1, 6):
                st.markdown(f"**문항 {i}**")
                if i in [1, 2, 5]: st.text_area(f"Q{i}", key=f"p4_q{i}", height=80)
                else: st.radio(f"Q{i}", ["1","2","3","4","5"], horizontal=True, key=f"p4_q{i}")
                st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key=f"p4_c{i}")
                st.markdown("---")

        elif info['type'] == 'part5_special':
            for i in [1, 2, 5]:
                st.markdown(f"**문항 {i}**")
                st.radio("(1)", ["1","2","3","4","5"], horizontal=True, key=f"p5_q{i}_obj")
                st.text_input("(2)", key=f"p5_q{i}_text")
                st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key=f"p5_c{i}")
                st.markdown("---")
            for i in [3, 4]:
                st.markdown(f"**문항 {i}**")
                st.text_input("정답", key=f"p5_q{i}_text")
                st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key=f"p5_c{i}")
                st.markdown("---")

        elif info['type'] == 'part6_sets':
            q_global = 1
            for s in range(1, 4):
                st.markdown(f"### [Set {s}]")
                st.text_input(f"Q{q_global} Keyword", key=f"p6_q{q_global}"); q_global+=1
                st.radio(f"Q{q_global} Tone", ["1","2","3","4","5"], horizontal=True, key=f"p6_q{q_global}"); q_global+=1
                st.radio(f"Q{q_global} Flow", ["1","2","3","4"], horizontal=True, key=f"p6_q{q_global}"); q_global+=1
                st.text_area(f"Q{q_global} Summary", key=f"p6_q{q_global}"); q_global+=1
                st.radio(f"Set {s} 확신도", ["확신", "애매", "모름"], horizontal=True, key=f"p6_set{s}_conf")
                st.markdown("---")

        elif info['type'] == 'simple_subj':
            for i in range(1, info['count']+1):
                st.markdown(f"**문항 {i}**")
                st.text_area(f"답안", key=f"p{part}_q{i}")
                st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key=f"p{part}_c{i}")
                st.markdown("---")

        # --- 제출 버튼 (이메일 기반 저장으로 변경됨) ---
        if st.form_submit_button(f"Part {part} 제출 및 저장"):
            final_data = []
            
            # 1. 단순 객관식/서술형 (Part 1, 7, 8)
            if info['type'] in ['simple_obj', 'simple_subj']:
                for i in range(1, info['count'] + 1):
                    final_data.append({
                        'q_id': str(i),
                        'ans': st.session_state.get(f"p{part}_q{i}", ""),
                        'conf': st.session_state.get(f"p{part}_c{i}", "모름")
                    })
            
            # 2. Part 2
            elif info['type'] == 'part2_special':
                for i in range(1, 10):
                    final_data.append({'q_id': str(i), 'ans': st.session_state.get(f"p2_q{i}", ""), 'conf': st.session_state.get(f"p2_c{i}", "모름")})
                final_data.append({'q_id': '10_wrong', 'ans': st.session_state.get("p2_q10_wrong", ""), 'conf': st.session_state.get("p2_c10", "모름")})
                final_data.append({'q_id': '10_correct', 'ans': st.session_state.get("p2_q10_correct", ""), 'conf': st.session_state.get("p2_c10", "모름")})

            # 3. Part 3
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

            # 4. Part 4
            elif info['type'] == 'part4_special':
                for i in range(1, 6):
                    final_data.append({'q_id': str(i), 'ans': st.session_state.get(f"p4_q{i}", ""), 'conf': st.session_state.get(f"p4_c{i}", "모름")})

            # 5. Part 5
            elif info['type'] == 'part5_special':
                for i in [1, 2, 5]:
                    final_data.append({'q_id': f"{i}_obj", 'ans': st.session_state.get(f"p5_q{i}_obj", ""), 'conf': st.session_state.get(f"p5_c{i}", "모름")})
                    final_data.append({'q_id': f"{i}_text", 'ans': st.session_state.get(f"p5_q{i}_text", ""), 'conf': st.session_state.get(f"p5_c{i}", "모름")})
                for i in [3, 4]:
                    final_data.append({'q_id': f"{i}_text", 'ans': st.session_state.get(f"p5_q{i}_text", ""), 'conf': st.session_state.get(f"p5_c{i}", "모름")})

            # 6. Part 6
            elif info['type'] == 'part6_sets':
                conf1 = st.session_state.get("p6_set1_conf", "모름")
                for i in range(1, 5): final_data.append({'q_id': str(i), 'ans': st.session_state.get(f"p6_q{i}", ""), 'conf': conf1})
                conf2 = st.session_state.get("p6_set2_conf", "모름")
                for i in range(5, 9): final_data.append({'q_id': str(i), 'ans': st.session_state.get(f"p6_q{i}", ""), 'conf': conf2})
                conf3 = st.session_state.get("p6_set3_conf", "모름")
                for i in range(9, 13): final_data.append({'q_id': str(i), 'ans': st.session_state.get(f"p6_q{i}", ""), 'conf': conf3})

            # 저장 실행
            try:
                with st.spinner("답안을 안전하게 저장 중입니다..."):
                    # 이메일 기반 저장 함수 호출
                    save_answers_bulk(st.session_state['user_email'], part, final_data)
                    st.session_state['current_part'] += 1
                    time.sleep(1) # 저장 안정성 확보
                    st.rerun()
            except Exception as e:
                st.error(f"데이터 저장 중 오류가 발생했습니다: {e}")
                st.warning("잠시 후 다시 시도해주세요. 오류가 지속되면 원장님께 문의 바랍니다.")

# ---------------------------------------------------------
# 화면 3: 완료 및 분석
# ---------------------------------------------------------
else:
    st.balloons()
    
    with st.spinner("최종 성적을 분석 중입니다..."):
        try:
            # 이메일 기반 분석 함수 호출
            df_res = calculate_results(st.session_state['user_email'])
            show_report_dashboard(df_res, st.session_state['user_name'])
        except Exception as e:
            st.error(f"분석 오류: {e}")
            st.info("아직 답안이 모두 제출되지 않았거나, 정답지 연결에 문제가 있습니다.")
    
    if st.button("처음으로"):
        st.session_state.clear()
        st.rerun()
