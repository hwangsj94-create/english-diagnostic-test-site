import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.graph_objects as go
import plotly.express as px
import time

# ==========================================
# [설정] 파트별 문항 상세 구성 & 전문가 분석 가이드
# ==========================================
EXAM_STRUCTURE = {
    1: {"title": "Part 1. 어휘력 (Vocabulary)", "type": "simple_obj", "count": 30, "level": "기초"},
    2: {"title": "Part 2. 어법 지식 (Grammar)", "type": "part2_special", "count": 10, "level": "기초"}, 
    3: {"title": "Part 3. 구문 해석력 (Syntax)", "type": "part3_special", "count": 5, "level": "중급"}, 
    4: {"title": "Part 4. 문해력 (Literacy)", "type": "part4_special", "count": 5, "level": "중급"}, 
    5: {"title": "Part 5. 문장 연계 (Connectivity)", "type": "part5_special", "count": 5, "level": "상급"}, 
    6: {"title": "Part 6. 지문 이해 (Macro-Reading)", "type": "part6_sets", "count": 3, "level": "상급"},
    7: {"title": "Part 7. 문제 풀이 (Strategy)", "type": "simple_obj", "count": 4, "level": "최상급"},
    8: {"title": "Part 8. 서술형 영작 (Writing)", "type": "simple_subj", "count": 5, "level": "최상급"}
}

QUADRANT_LABELS = {
    "Master": "실력자 (The Ace)",
    "Lucky": "불안한 잠재력 (Anxious Potential)",
    "Delusion": "위험한 착각 (Critical Delusion)",
    "Deficiency": "백지 상태 (Blank Slate)"
}

# ==========================================
# 1. DB 연결 및 유틸리티
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

def get_student(name, email):
    try:
        sh = get_db_connection()
        ws = sh.worksheet("students")
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        if 'email' in df.columns:
            df['email'] = df['email'].astype(str).str.strip().str.lower()
            df['name'] = df['name'].astype(str).str.strip()
            student = df[(df['name'] == name.strip()) & (df['email'] == email.strip().lower())]
            return student.iloc[0].to_dict() if not student.empty else None
        return None
    except:
        return None

def save_student(name, email, school, grade):
    sh = get_db_connection()
    ws = sh.worksheet("students")
    email = email.strip().lower()
    try:
        cell = ws.find(email)
        ws.update_cell(cell.row, 2, name)
        ws.update_cell(cell.row, 3, school)
        ws.update_cell(cell.row, 4, grade)
    except:
        ws.append_row([email, name, school, grade, 1])

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
    if 'email' in df.columns:
        df['email'] = df['email'].astype(str).str.strip().str.lower()
        return df[df['email'] == str(email).strip().lower()]
    return pd.DataFrame()

# ==========================================
# 2. 입시 전문가형 분석 로직 (Deep Analysis)
# ==========================================
def calculate_results(email):
    student_ans_df = load_student_answers(email)
    key_df = load_answer_key()
    results = []
    
    if student_ans_df.empty: return pd.DataFrame()

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
            if user_ans.replace(" ", "").lower() == correct_ans.replace(" ", "").lower(): is_correct = True
        elif grading_type == 'strict':
            if user_ans.strip() == correct_ans.strip(): is_correct = True
        elif grading_type == 'ai_match':
            if keywords:
                req_words = [k.strip() for k in keywords.split(',')]
                match_cnt = sum(1 for w in req_words if w in user_ans)
                if match_cnt >= len(req_words) * 0.7: is_correct = True
            else:
                if len(user_ans) > 5: is_correct = True
        
        quadrant = ""
        if is_correct: quadrant = "Master" if conf == "확신" else "Lucky"
        else: quadrant = "Delusion" if conf == "확신" else "Deficiency"
            
        results.append({'part': int(part), 'q_id': q_id, 'is_correct': is_correct, 'quadrant': quadrant})
        
    return pd.DataFrame(results)

def generate_expert_analysis(df_results, student_name):
    # 파트별 점수 계산
    part_scores = df_results.groupby('part')['is_correct'].mean() * 100
    all_parts = pd.Series(0, index=range(1, 9))
    part_scores = part_scores.combine_first(all_parts).sort_index()

    # 메타인지 통계
    quad_counts = df_results['quadrant'].value_counts()
    master_ratio = (quad_counts.get("Master", 0) / len(df_results)) * 100
    delusion_ratio = (quad_counts.get("Delusion", 0) / len(df_results)) * 100
    lucky_ratio = (quad_counts.get("Lucky", 0) / len(df_results)) * 100
    
    # ----------------------------------------------------
    # 1. 예상 등급 및 근거 (난이도 위계 분석)
    # ----------------------------------------------------
    # 전략: P1,2(기초) -> P3,4(구문) -> P5,6(논리) -> P7,8(킬러) 순서로 무너진 지점을 찾음
    
    score_p12 = part_scores[1:3].mean()
    score_p34 = part_scores[3:5].mean()
    score_p56 = part_scores[5:7].mean()
    score_p78 = part_scores[7:9].mean()
    
    predicted_grade = ""
    grade_analysis = ""

    if score_p12 < 70:
        predicted_grade = "5등급 이하 (기초 재건 필요)"
        grade_analysis = f"냉정하게 평가할 때, {student_name} 학생은 영어의 기초 체력인 '어휘'와 '어법' 파트(Part 1~2)에서부터 흔들리고 있습니다. 이는 상위권 도약을 논하기 이전에, 중등 수준의 기초가 완성되지 않았음을 의미합니다. 특히 Part 1, 2가 무너진 상태에서는 Part 6, 7의 독해 점수가 높게 나오더라도 이는 '감'에 의존한 일시적 성과일 확률이 높습니다."
    elif score_p34 < 70:
        predicted_grade = "4등급 (구문 독해력 부족)"
        grade_analysis = f"어휘는 어느 정도 갖추었으나, 문장을 구조적으로 파악하는 '구문 해석력(Part 3~4)'에서 한계를 보입니다. 단어만 연결해서 해석하는 '감독해' 습관이 고착화되어 있을 가능성이 큽니다. 이 경우, 고1 수준의 문장은 해석하지만, 문장이 조금만 길어지거나 도치/생략 구문이 나오면 오독하게 되어 3등급의 벽을 넘기 어렵습니다."
    elif score_p56 < 70:
        predicted_grade = "3등급 (논리력 부재)"
        grade_analysis = f"문장 단위의 해석은 가능하지만, 문장과 문장 사이의 연결 고리를 파악하는 '논리적 독해력(Part 5~6)'이 부족합니다. 이는 글의 주제를 찾거나 빈칸을 추론할 때 결정적인 감점 요인이 됩니다. 2등급으로 올라서기 위해서는 단순 번역이 아니라, 필자의 의도와 글의 전개 방식을 파악하는 '거시적 독해 훈련'이 필수적입니다."
    elif score_p78 < 70:
        predicted_grade = "2등급 (킬러 문항 취약)"
        grade_analysis = f"전반적으로 우수한 실력을 갖추고 있으나, 변별력을 가르는 '고난도 문제 해결(Part 7)'과 '정밀 영작(Part 8)'에서 약점을 보입니다. 이는 1등급을 결정짓는 최후의 관문입니다. 특히 Part 8 서술형에서의 감점은 문법적 디테일 부족에서 기인하며, 이는 내신 1등급 방어에 치명적일 수 있습니다."
    else:
        predicted_grade = "1등급 (최상위권)"
        grade_analysis = f"기초부터 심화까지 전 영역에서 빈틈없는 실력을 보여주고 있습니다. 특히 킬러 파트인 Part 7, 8까지 완벽하게 소화해낸 점은 단순한 영어 실력을 넘어 논리적 사고력과 꼼꼼함까지 겸비했음을 증명합니다."

    # 메타인지 데이터를 근거에 추가
    grade_analysis += f"\n\n또한 메타인지 분석 결과, '위험한 착각(Delusion)' 비율이 {delusion_ratio:.1f}%로 나타났습니다. "
    if delusion_ratio > 20:
        grade_analysis += "이는 학생이 틀렸음에도 맞았다고 확신하는 비율이 매우 높다는 뜻으로, 시험장에서 예상 점수보다 실제 점수가 대폭 하락할 수 있는 '거품'이 끼어 있음을 시사합니다. 이 오개념을 걷어내지 않으면 등급 상승은 요원합니다."
    elif lucky_ratio > 30:
        grade_analysis += "이는 자신의 실력보다 운에 의존하여 정답을 맞힌 비율(불안한 잠재력)이 높다는 뜻입니다. 현재 점수는 학생의 진짜 실력이 아닐 수 있으며, 난이도가 조금만 높아져도 점수가 급락할 위험이 있습니다."
    else:
        grade_analysis += "자신이 아는 것과 모르는 것을 명확히 구분하는 메타인지 능력이 양호하여, 학습 효율이 매우 높을 것으로 기대됩니다."

    # ----------------------------------------------------
    # 2. 영역별 역량 분석 텍스트 (300자 이상)
    # ----------------------------------------------------
    # 가장 약한 파트 찾기
    weakest_part = part_scores.idxmin()
    weakest_score = part_scores.min()
    
    area_text = f"학생의 8개 영역 성취도를 분석한 결과, 가장 시급한 보완이 필요한 영역은 **[{EXAM_STRUCTURE[weakest_part]['title']}]**입니다. 현재 이 파트의 점수는 {int(weakest_score)}점으로, 다른 영역에 비해 현저히 낮습니다.\n\n"
    
    if weakest_part in [1, 2]:
        area_text += "어휘와 어법은 영어 학습의 뿌리입니다. 뿌리가 약하면 구문 독해(Part 3,4)나 논리 독해(Part 5,6)로 나아갈 수 없습니다. 현재 학생은 고등 영어를 받아들일 기초 체력이 부족하므로, 당분간 문제 풀이보다는 단어 암기와 문법 개념 정리에 학습 시간의 80%를 할애해야 합니다."
    elif weakest_part in [3, 4]:
        area_text += "구문 해석력이 약하다는 것은 '정확한 독해'가 안 된다는 뜻입니다. 대충 아는 단어들을 조합해 소설을 쓰는 식의 독해를 하고 있을 가능성이 높습니다. 주어와 동사를 정확히 찾고, 수식 구조를 괄호 묶는 훈련(Chunking)을 집중적으로 수행해야 합니다. 이것이 해결되지 않으면 고학년이 될수록 점수 정체기에 빠지게 됩니다."
    elif weakest_part in [5, 6]:
        area_text += "문맥 파악과 논리적 연결성이 부족합니다. 해석은 했는데 '그래서 무슨 말이지?'라고 되묻는 경우가 많을 것입니다. 글의 소재(Keyword), 태도(Tone), 전개 구조(Flow)를 분석하는 훈련을 통해 글을 입체적으로 읽는 눈을 길러야 합니다."
    elif weakest_part in [7, 8]:
        area_text += "최상위권 도약을 위한 마지막 퍼즐이 빠져 있습니다. 특히 서술형 영작(Part 8)에서의 감점은 내신 등급 결정에 치명적입니다. 문법 지식을 단순히 아는 것(Input)을 넘어, 조건에 맞춰 정확하게 문장을 구성해내는(Output) 훈련이 필요합니다. 사소한 수일치, 태, 시제 실수를 잡는 정밀 클리닉이 요구됩니다."

    area_text += f"\n\n반면, **[{EXAM_STRUCTURE[part_scores.idxmax()]['title']}]** 영역에서는 {int(part_scores.max())}점의 우수한 성취도를 보였습니다. 강점 영역을 유지하되, 취약 영역인 Part {weakest_part}와의 불균형을 해소하는 것이 전체 등급 상승의 열쇠가 될 것입니다."

    # ----------------------------------------------------
    # 3. 메타인지 분석 텍스트 (300자 이상)
    # ----------------------------------------------------
    meta_text = f"단순 정답률보다 더 중요한 것이 '확신도(Confidence)'입니다. {student_name} 학생의 응답 데이터를 4분면으로 분석했을 때, 전문가로서 주목하는 지점은 다음과 같습니다.\n\n"
    
    meta_text += f"첫째, **'위험한 착각(Critical Delusion)' 비율이 {delusion_ratio:.1f}%**입니다. "
    if delusion_ratio > 15:
        meta_text += "이 수치가 높다는 것은 '잘못된 지식의 고착화'를 의미합니다. 학생은 틀린 문법이나 독해 습관을 옳다고 믿고 있어, 일반적인 강의 수강만으로는 교정이 어렵습니다. 반드시 1:1 클리닉을 통해 왜 그렇게 생각했는지 사고 과정을 역추적하여 오개념을 깨뜨려야 합니다. "
    else:
        meta_text += "이는 비교적 양호한 수준으로, 학생이 자신의 부족함을 솔직하게 인정하고 있음을 보여줍니다. 이러한 태도는 학습 흡수력을 높여줍니다. "
        
    meta_text += f"\n\n둘째, **'불안한 잠재력(Anxious Potential)' 비율이 {lucky_ratio:.1f}%**입니다. "
    if lucky_ratio > 20:
        meta_text += "맞힌 문제 중 상당수가 '찍어서' 혹은 '감으로' 맞힌 것입니다. 시험 운이 좋았을 뿐, 이것을 실력으로 착각해서는 안 됩니다. 이 영역은 조금만 훈련하면 '실력자(The Ace)' 영역으로 가장 빠르게 전환될 수 있는 '기회의 땅'입니다. 해당 문항들에 대해 확신을 가질 수 있도록 개념 강화 학습이 필요합니다."
    else:
        meta_text += "학생은 자신이 아는 내용에 대해서는 확신을 가지고 정답을 골랐습니다. 이는 학습 내용이 내면화가 잘 되어 있음을 방증합니다."
        
    meta_text += "\n\n결론적으로, 점수 뒤에 숨겨진 이 메타인지 패턴을 이해해야 합니다. 모르는 건 죄가 아니지만, '안다고 착각하는 것'은 입시에서 가장 큰 적입니다. 이번 진단은 이 '착각'을 수치화하여 보여주었다는 점에서 큰 의미가 있습니다."

    return predicted_grade, grade_analysis, area_text, meta_text

# ==========================================
# 4. 리포트 UI 컴포넌트
# ==========================================
def show_report_dashboard(df_results, student_name):
    # PDF 저장을 위한 JS 스크립트 (화면 인쇄 기능 호출)
    st.markdown("""
    <script>
    function printPage() {
        window.print();
    }
    </script>
    """, unsafe_allow_html=True)

    st.markdown(f"## 📊 {student_name}님의 영어 역량 정밀 진단 리포트")
    
    if df_results.empty:
        st.warning("분석할 데이터가 없습니다.")
        return

    pred_grade, grade_txt, area_txt, meta_txt = generate_expert_analysis(df_results, student_name)
    
    total_q = len(df_results)
    correct_q = len(df_results[df_results['is_correct'] == True])
    score = int((correct_q / total_q) * 100) if total_q > 0 else 0
    
    # 1. 요약 카드
    col1, col2, col3, col4 = st.columns([2, 2, 3, 2])
    col1.metric("종합 점수", f"{score}점")
    col2.metric("정답 수", f"{correct_q} / {total_q}")
    col3.metric("예상 등급", pred_grade.split('(')[0])
    with col4:
        # PDF 저장 버튼 (브라우저 인쇄 트리거)
        st.button("🖨️ PDF로 저장", on_click=None, help="버튼을 누른 후 '대상'을 'PDF로 저장'으로 변경하세요.", type="primary", args=None, kwargs=None, key="print_btn")
        if st.session_state.get("print_btn"):
            st.components.v1.html("<script>window.print();</script>", height=0, width=0)

    st.divider()
    
    # 2. 등급 분석 및 근거
    st.subheader("1. 예상 등급 분석 및 근거")
    st.info(grade_txt)
    st.divider()

    # 3. 영역별 역량 분석 (막대 그래프)
    c_graph1, c_graph2 = st.columns([1, 1])
    
    with c_graph1:
        st.subheader("2. 영역별 역량 분석")
        part_stats = df_results.groupby('part')['is_correct'].mean() * 100
        all_parts = pd.Series(0, index=range(1, 9))
        part_stats = part_stats.combine_first(all_parts).sort_index()
        
        # 막대 그래프 데이터 생성
        df_bar = pd.DataFrame({
            '영역': [EXAM_STRUCTURE[p]['title'].split('.')[1].strip() for p in range(1,9)],
            '점수': part_stats.values,
            'Color': part_stats.values
        })
        
        fig_bar = px.bar(df_bar, x='영역', y='점수', text='점수', color='점수', 
                         color_continuous_scale='Blues', range_y=[0, 100])
        fig_bar.update_traces(texttemplate='%{text:.0f}점', textposition='outside')
        fig_bar.update_layout(xaxis_tickangle=-45, showlegend=False)
        st.plotly_chart(fig_bar, use_container_width=True)
        
    with c_graph2:
        st.markdown("**[전문가 진단]**")
        st.write(area_txt)

    st.divider()

    # 4. 메타인지 분석
    c_meta1, c_meta2 = st.columns([1, 1])
    
    with c_meta1:
        st.subheader("3. 메타인지(확신도) 분석")
        
        # 내부 용어를 한국어 라벨로 매핑
        df_results['quadrant_label'] = df_results['quadrant'].map(QUADRANT_LABELS)
        quad_counts = df_results['quadrant_label'].value_counts()
        
        colors = {
            QUADRANT_LABELS["Master"]: '#28a745',     # 녹색
            QUADRANT_LABELS["Lucky"]: '#ffc107',      # 노랑
            QUADRANT_LABELS["Delusion"]: '#dc3545',   # 빨강
            QUADRANT_LABELS["Deficiency"]: '#6c757d'  # 회색
        }
        
        fig_pie = px.pie(names=quad_counts.index, values=quad_counts.values, hole=0.4, 
                         color=quad_counts.index, color_discrete_map=colors)
        fig_pie.update_traces(textinfo='percent+label')
        st.plotly_chart(fig_pie, use_container_width=True)

    with c_meta2:
        st.markdown("**[전문가 진단]**")
        st.write(meta_txt)

    st.markdown("""
    > **※ 메타인지 그래프 해석**
    > * **실력자:** 정답+확신 (안정적 득점원)
    > * **불안한 잠재력:** 정답+비확신 (실수로 이어질 가능성)
    > * **위험한 착각:** 오답+확신 (교정이 가장 시급한 고집 센 오답)
    > * **백지 상태:** 오답+비확신 (기초 학습 필요)
    """)

# ==========================================
# 5. 메인 앱 실행
# ==========================================
st.set_page_config(page_title="영어 역량 정밀 진단", layout="wide")

st.markdown("""
<style>
div.row-widget.stRadio > div {flex-direction: row;} 
div.row-widget.stRadio > div > label {
    background-color: #f8f9fa; padding: 10px 20px; border-radius: 8px; margin-right: 8px; cursor: pointer; border: 1px solid #dee2e6;
}
div.row-widget.stRadio > div > label:hover {background-color: #e9ecef;}
textarea {font-size: 16px !important; line-height: 1.5 !important;}
input[type="text"] {font-size: 16px !important;}
.stAlert {font-weight: bold;}
/* 인쇄 시 버튼 숨기기 */
@media print {
    button { display: none !important; }
    .stApp { margin: 0; padding: 0; }
}
</style>
""", unsafe_allow_html=True)

if 'user_email' not in st.session_state: st.session_state['user_email'] = None
if 'user_name' not in st.session_state: st.session_state['user_name'] = None
if 'current_part' not in st.session_state: st.session_state['current_part'] = 1
if 'view_mode' not in st.session_state: st.session_state['view_mode'] = False

# ---------------------------------------------------------
# 화면 1: 로그인
# ---------------------------------------------------------
if st.session_state['user_email'] is None:
    st.title("🎓 영어 역량 정밀 진단고사")
    st.info("로그인 시 이메일 주소를 사용합니다. (예: student@naver.com)")
    
    tab1, tab2 = st.tabs(["시험 응시 / 이어하기", "내 결과 확인하기"])
    
    with tab1:
        with st.form("login_form"):
            name = st.text_input("이름")
            email = st.text_input("이메일 주소")
            
            # [수정] 학교 직접 입력 로직
            col_s1, col_s2 = st.columns([1, 1])
            with col_s1:
                school_opt = st.radio("학교 선택", ["신원고등학교", "동산고등학교", "직접 입력"])
            with col_s2:
                custom_school = st.text_input("학교명 (직접 입력 시 작성)")
            
            grade = st.selectbox("학년 (2026년 기준)", ["중3", "고1", "고2", "고3"])
            
            if st.form_submit_button("진단 시작하기"):
                if name and email:
                    final_school = custom_school if school_opt == "직접 입력" else school_opt
                    if school_opt == "직접 입력" and not custom_school:
                        st.error("학교명을 입력해주세요.")
                    elif "@" not in email:
                        st.error("올바른 이메일 형식이 아닙니다.")
                    else:
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
    
    st.title(f"{info['title']}")
    st.progress(part / 8)
    
    # [수정] Part 8 상단 주의사항 강조
    if part == 8:
        st.error("""
        **[⚠️ 서술형 답안 작성 주의사항]**
        1. 문장의 끝에는 **반드시 마침표(.)**를 찍어야 합니다.
        2. **띄어쓰기**나 줄바꿈 실수는 오답 처리됩니다. (엔터키 주의)
        3. 조건에 맞지 않는 답안은 0점 처리됩니다.
        """)

    with st.form(f"exam_form_{part}"):
        # TYPE 1: 단순 객관식
        if info['type'] == 'simple_obj':
            st.info(f"총 {info['count']}문항입니다.")
            for i in range(1, info['count'] + 1):
                st.markdown(f"**문항 {i}**")
                c1, c2 = st.columns([3, 1])
                with c1: st.radio(f"Q{i} 정답", ["1","2","3","4","5"], horizontal=True, key=f"p{part}_q{i}", label_visibility="collapsed")
                with c2: st.radio(f"확신도", ["확신", "애매", "모름"], horizontal=False, key=f"p{part}_c{i}", label_visibility="collapsed")
                st.markdown("---")

        # TYPE 2: Part 2
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

        # TYPE 3: Part 3
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

        # TYPE 4: Part 4
        elif info['type'] == 'part4_special':
            for i in range(1, 6):
                st.markdown(f"**문항 {i}**")
                if i in [1, 2, 5]: st.text_area(f"Q{i}", key=f"p4_q{i}", height=80)
                else: st.radio(f"Q{i}", ["1","2","3","4","5"], horizontal=True, key=f"p4_q{i}")
                st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key=f"p4_c{i}")
                st.markdown("---")

        # TYPE 5: Part 5 (순서 정렬 수정: 1, 2, 3, 4, 5)
        elif info['type'] == 'part5_special':
            # 1, 2번 (복합)
            for i in [1, 2]:
                st.markdown(f"**문항 {i}**")
                st.radio("(1)", ["1","2","3","4","5"], horizontal=True, key=f"p5_q{i}_obj")
                st.text_input("(2)", key=f"p5_q{i}_text")
                st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key=f"p5_c{i}")
                st.markdown("---")
            # 3, 4번 (단독) - 순서대로 배치
            for i in [3, 4]:
                st.markdown(f"**문항 {i}**")
                st.text_input("정답", key=f"p5_q{i}_text")
                st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key=f"p5_c{i}")
                st.markdown("---")
            # 5번 (복합)
            st.markdown(f"**문항 5**")
            st.radio("(1)", ["1","2","3","4","5"], horizontal=True, key=f"p5_q5_obj")
            st.text_input("(2)", key=f"p5_q5_text")
            st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key=f"p5_c5")
            st.markdown("---")

        # TYPE 6: Part 6
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

        # TYPE 8: Part 8
        elif info['type'] == 'simple_subj':
            for i in range(1, info['count']+1):
                st.markdown(f"**문항 {i}**")
                st.text_area(f"답안", key=f"p{part}_q{i}")
                st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key=f"p{part}_c{i}")
                st.markdown("---")

        # ==========================================
        # 제출 및 저장
        # ==========================================
        if st.form_submit_button(f"Part {part} 제출 및 저장"):
            final_data = []
            is_valid = True
            
            # --- 데이터 수집 로직 ---
            if info['type'] in ['simple_obj', 'simple_subj']:
                for i in range(1, info['count'] + 1):
                    ans = st.session_state.get(f"p{part}_q{i}", "")
                    conf = st.session_state.get(f"p{part}_c{i}", "모름")
                    if not ans: is_valid = False
                    final_data.append({'q_id': str(i), 'ans': ans, 'conf': conf})
            
            elif info['type'] == 'part2_special':
                for i in range(1, 10):
                    ans = st.session_state.get(f"p2_q{i}", "")
                    if not ans: is_valid = False
                    final_data.append({'q_id': str(i), 'ans': ans, 'conf': st.session_state.get(f"p2_c{i}", "모름")})
                
                ans_w = st.session_state.get("p2_q10_wrong", "")
                ans_c = st.session_state.get("p2_q10_correct", "")
                if not ans_w or not ans_c: is_valid = False
                final_data.append({'q_id': '10_wrong', 'ans': ans_w, 'conf': st.session_state.get("p2_c10", "모름")})
                final_data.append({'q_id': '10_correct', 'ans': ans_c, 'conf': st.session_state.get("p2_c10", "모름")})

            elif info['type'] == 'part3_special':
                # Q1
                a1s = st.session_state.get("p3_q1_subj", ""); a1v = st.session_state.get("p3_q1_verb", ""); a1o = st.session_state.get("p3_q1_obj", "")
                if not (a1s and a1v and a1o): is_valid = False
                final_data.append({'q_id': '1_subj', 'ans': a1s, 'conf': st.session_state.get("p3_c1", "모름")})
                final_data.append({'q_id': '1_verb', 'ans': a1v, 'conf': st.session_state.get("p3_c1", "모름")})
                final_data.append({'q_id': '1_obj', 'ans': a1o, 'conf': st.session_state.get("p3_c1", "모름")})
                # Q2
                a2s = st.session_state.get("p3_q2_subj", ""); a2v = st.session_state.get("p3_q2_verb", ""); a2o = st.session_state.get("p3_q2_obj", "")
                if not (a2s and a2v and a2o): is_valid = False
                final_data.append({'q_id': '2_subj', 'ans': a2s, 'conf': st.session_state.get("p3_c2", "모름")})
                final_data.append({'q_id': '2_verb', 'ans': a2v, 'conf': st.session_state.get("p3_c2", "모름")})
                final_data.append({'q_id': '2_obj', 'ans': a2o, 'conf': st.session_state.get("p3_c2", "모름")})
                # Q3
                a3s = st.session_state.get("p3_q3_subj", ""); a3o = st.session_state.get("p3_q3_obj", "")
                if not (a3s and a3o): is_valid = False
                final_data.append({'q_id': '3_subj', 'ans': a3s, 'conf': st.session_state.get("p3_c3", "모름")})
                final_data.append({'q_id': '3_obj', 'ans': a3o, 'conf': st.session_state.get("p3_c3", "모름")})
                # Q4
                a4s = st.session_state.get("p3_q4_subj", ""); a4v = st.session_state.get("p3_q4_verb", ""); a4o = st.session_state.get("p3_q4_obj", "")
                if not (a4s and a4v and a4o): is_valid = False
                final_data.append({'q_id': '4_subj', 'ans': a4s, 'conf': st.session_state.get("p3_c4", "모름")})
                final_data.append({'q_id': '4_verb', 'ans': a4v, 'conf': st.session_state.get("p3_c4", "모름")})
                final_data.append({'q_id': '4_obj', 'ans': a4o, 'conf': st.session_state.get("p3_c4", "모름")})
                # Q5
                a5o = st.session_state.get("p3_q5_obj", ""); a5t = st.session_state.get("p3_q5_text", "")
                if not (a5o and a5t): is_valid = False
                final_data.append({'q_id': '5_obj', 'ans': a5o, 'conf': st.session_state.get("p3_c5", "모름")})
                final_data.append({'q_id': '5_text', 'ans': a5t, 'conf': st.session_state.get("p3_c5", "모름")})

            elif info['type'] == 'part4_special':
                for i in range(1, 6):
                    ans = st.session_state.get(f"p4_q{i}", "")
                    if not ans: is_valid = False
                    final_data.append({'q_id': str(i), 'ans': ans, 'conf': st.session_state.get(f"p4_c{i}", "모름")})

            elif info['type'] == 'part5_special':
                # 1,2,5번 복합
                for i in [1, 2, 5]:
                    ao = st.session_state.get(f"p5_q{i}_obj", "")
                    at = st.session_state.get(f"p5_q{i}_text", "")
                    if not (ao and at): is_valid = False
                    final_data.append({'q_id': f"{i}_obj", 'ans': ao, 'conf': st.session_state.get(f"p5_c{i}", "모름")})
                    final_data.append({'q_id': f"{i}_text", 'ans': at, 'conf': st.session_state.get(f"p5_c{i}", "모름")})
                # 3,4번 단독
                for i in [3, 4]:
                    at = st.session_state.get(f"p5_q{i}_text", "")
                    if not at: is_valid = False
                    final_data.append({'q_id': f"{i}_text", 'ans': at, 'conf': st.session_state.get(f"p5_c{i}", "모름")})

            elif info['type'] == 'part6_sets':
                c1 = st.session_state.get("p6_set1_conf", "모름")
                c2 = st.session_state.get("p6_set2_conf", "모름")
                c3 = st.session_state.get("p6_set3_conf", "모름")
                
                for i in range(1, 5):
                    ans = st.session_state.get(f"p6_q{i}", "")
                    if not ans: is_valid = False
                    final_data.append({'q_id': str(i), 'ans': ans, 'conf': c1})
                for i in range(5, 9):
                    ans = st.session_state.get(f"p6_q{i}", "")
                    if not ans: is_valid = False
                    final_data.append({'q_id': str(i), 'ans': ans, 'conf': c2})
                for i in range(9, 13):
                    ans = st.session_state.get(f"p6_q{i}", "")
                    if not ans: is_valid = False
                    final_data.append({'q_id': str(i), 'ans': ans, 'conf': c3})

            # [수정] 빈칸 방지 로직
            if not is_valid:
                st.error("⚠️ 모든 문항의 정답을 입력해야 제출할 수 있습니다. 빠진 부분이 없는지 확인해주세요.")
            else:
                try:
                    with st.spinner("답안을 안전하게 저장 중입니다..."):
                        save_answers_bulk(st.session_state['user_email'], part, final_data)
                        st.session_state['current_part'] += 1
                        time.sleep(1) 
                        st.rerun()
                except Exception as e:
                    st.error(f"데이터 저장 중 오류가 발생했습니다: {e}")

# ---------------------------------------------------------
# 화면 3: 완료 및 분석
# ---------------------------------------------------------
else:
    st.balloons()
    
    with st.spinner("최종 성적을 분석 중입니다..."):
        try:
            df_res = calculate_results(st.session_state['user_email'])
            show_report_dashboard(df_res, st.session_state['user_name'])
        except Exception as e:
            st.error(f"분석 오류: {e}")
            st.info("아직 답안이 모두 제출되지 않았거나, 정답지 연결에 문제가 있습니다.")
    
    if st.button("처음으로"):
        st.session_state.clear()
        st.rerun()
