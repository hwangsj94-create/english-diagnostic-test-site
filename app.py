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

# 메타인지 매트릭스 정의 (이미지 기반)
QUADRANT_LABELS = {
    "Master": "실력자 (The Ace)",
    "Lucky": "불안한 잠재력 (Anxious Potential)",
    "Delusion": "위험한 착각 (Critical Delusion)",
    "Deficiency": "백지 상태 (Blank Slate)"
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

def get_student(name, email):
    try:
        sh = get_db_connection()
        ws = sh.worksheet("students")
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        
        name = name.strip()
        email = email.strip().lower()
        
        if 'email' in df.columns:
            df['email'] = df['email'].astype(str).str.strip().str.lower()
            df['name'] = df['name'].astype(str).str.strip()
            student = df[(df['name'] == name) & (df['email'] == email)]
            return student.iloc[0].to_dict() if not student.empty else None
        else:
            return None
    except:
        return None

def save_student(name, email, school, grade):
    sh = get_db_connection()
    ws = sh.worksheet("students")
    name = name.strip()
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

# ==========================================
# 3. 자동 텍스트 생성기 (500자 이상 로직)
# ==========================================
def generate_verbose_analysis(df_results):
    # 통계 계산
    total_q = len(df_results)
    correct_q = len(df_results[df_results['is_correct'] == True])
    score = int((correct_q / total_q) * 100) if total_q > 0 else 0
    
    quad_counts = df_results['quadrant'].value_counts()
    master_cnt = quad_counts.get("Master", 0)
    delusion_cnt = quad_counts.get("Delusion", 0)
    lucky_cnt = quad_counts.get("Lucky", 0)
    deficiency_cnt = quad_counts.get("Deficiency", 0)
    
    # 1. 예상 등급 근거 (500자 이상)
    grade_text = f"현재 학생의 종합 점수는 {score}점이며, 전체 문항 중 정답률은 {int((correct_q/total_q)*100)}%입니다. "
    
    if score >= 90:
        grade_text += "이 점수는 안정적인 1등급 구간에 해당합니다. 특히 주목할 점은 '실력자(The Ace)' 유형의 비율이 높다는 점입니다. 이는 학생이 문제를 풀 때 단순히 감에 의존하는 것이 아니라, 명확한 근거와 논리를 바탕으로 정답을 도출해내고 있음을 시사합니다. "
    elif score >= 80:
        grade_text += "이 점수는 2등급 초반에서 1등급 턱걸이 구간에 해당합니다. 전반적인 이해도는 우수하나, 일부 고난도 유형에서 확신이 부족하거나 오개념이 발견됩니다. 1등급으로 확실히 도약하기 위해서는 '불안한 잠재력' 영역을 '실력자' 영역으로 전환하는 정밀 학습이 필요합니다. "
    elif score >= 70:
        grade_text += "이 점수는 3등급 상위권에서 2등급 하위권 구간으로 예측됩니다. 기본적인 어휘와 문법 지식은 갖추고 있으나, 복합적인 사고를 요하는 문항에서 오답률이 높습니다. 특히 틀린 문제 중 상당수가 '위험한 착각'에 해당한다면, 이는 잘못된 지식이 고착화되어 있음을 의미하므로 시급한 교정이 필요합니다. "
    else:
        grade_text += "현재 점수대는 4등급 이하 구간으로, 영어 기초 체력 강화가 절실한 단계입니다. 단순 암기보다는 문장의 구조를 보는 눈을 기르고, '백지 상태'인 영역을 차근차근 채워나가는 학습 전략이 필요합니다. "

    grade_text += f"\n\n상세 분석 결과, 학생은 전체 문항 중 {delusion_cnt}개 문항에서 '위험한 착각(Delusion)' 반응을 보였습니다. 이는 틀렸음에도 불구하고 정답이라고 확신한 경우로, 시험장에서 등급을 떨어뜨리는 가장 치명적인 요인입니다. 반면 {lucky_cnt}개 문항은 '불안한 잠재력(Lucky)'으로 분류되었습니다. 이는 정답은 맞혔으나 확신이 없는 상태로, 컨디션에 따라 언제든 오답으로 바뀔 수 있는 불안 요소입니다. 따라서 예상 등급을 단순히 점수로만 판단하기보다, 이러한 메타인지 데이터를 종합적으로 고려했을 때 {score}점이라는 점수는 학생의 실제 영어 실력을 나타내는 지표이자 앞으로의 학습 방향성을 제시하는 나침반이 될 것입니다."
    grade_text += "\n\n결론적으로, 현재 등급을 유지하거나 상승시키기 위해서는 자신이 '안다고 착각하는 것'과 '실제로 아는 것'을 철저히 구분하는 메타인지 훈련이 선행되어야 하며, 이를 통해 실수를 줄이고 정답의 근거를 명확히 하는 연습을 지속해야 합니다."

    # 2. 파트별 분석 (각 파트별 상세 텍스트)
    part_analysis_text = ""
    for p in range(1, 9):
        p_df = df_results[df_results['part'] == p]
        if p_df.empty: continue
        
        p_score = int(p_df['is_correct'].mean() * 100)
        p_quads = p_df['quadrant'].value_counts()
        dom_quad = p_quads.idxmax() if not p_quads.empty else "None"
        
        title = EXAM_STRUCTURE[p]['title']
        part_analysis_text += f"\n\n**[{title} - {p_score}점]**\n"
        part_analysis_text += f"이 영역에서 학생은 {p_score}점의 성취도를 보였습니다. "
        
        if dom_quad == "Master":
            part_analysis_text += "가장 두드러진 특징은 '실력자(The Ace)' 유형의 응답이 많다는 것입니다. 이는 해당 파트의 핵심 개념을 정확히 이해하고 있으며, 실전에서도 흔들림 없이 정답을 골라낼 수 있는 탄탄한 실력을 갖추고 있음을 의미합니다. 현재의 학습 방식을 유지하되, 고난도 킬러 문항 대비를 병행한다면 완벽한 만점을 기대할 수 있습니다. "
        elif dom_quad == "Lucky":
            part_analysis_text += "주목할 점은 정답을 맞힌 문항 중 다수가 '불안한 잠재력(Anxious Potential)'에 해당한다는 것입니다. 이는 '감'으로 문제를 풀고 있거나, 개념을 어렴풋이만 알고 있는 상태입니다. 운 좋게 점수는 나왔을지 모르나, 이는 모래 위에 쌓은 성과 같습니다. 정확한 구문 분석과 어휘 학습을 통해 근거를 찾는 훈련이 시급합니다. "
        elif dom_quad == "Delusion":
            part_analysis_text += "가장 우려되는 점은 '위험한 착각(Critical Delusion)' 유형의 비율이 높다는 것입니다. 학생은 자신이 개념을 잘 알고 있다고 생각하지만, 실제로는 오개념을 가지고 있거나 출제자의 함정에 쉽게 빠지는 경향이 있습니다. 이는 혼자서 공부할 때 교정하기 가장 어려운 유형이므로, 전문가의 피드백을 통해 잘못된 개념을 뿌리 뽑아야 합니다. "
        elif dom_quad == "Deficiency":
            part_analysis_text += "이 파트는 '백지 상태(Blank Slate)'로 분류되는 문항이 많습니다. 즉, 해당 영역에 대한 기초 학습이 전반적으로 부족한 상태입니다. 무리하게 문제 풀이 양을 늘리기보다는, 기본 개념서로 돌아가 용어 정의와 원리를 차근차근 학습하는 것이 점수 향상의 지름길입니다. "
            
        part_analysis_text += "세부적으로 살펴보면, 학생은 이 파트에서 요구하는 논리적 사고력과 응용력 부분에서 강점/약점을 보이고 있습니다. (이 부분은 문항별 세부 분석을 통해 더 구체화될 수 있습니다). 특히 이 영역은 수능 및 내신 등급을 가르는 핵심 파트이므로, 위에서 분석한 메타인지 유형에 맞춰 학습 우선순위를 재조정해야 합니다. 단순히 많이 푸는 것보다 '왜 틀렸는지', '왜 맞았는지'를 스스로 설명할 수 있을 때까지 집요하게 파고드는 학습 태도가 필요합니다."

    # 3. 총평 (500자 이상)
    total_review = f"종합적으로 {st.session_state['user_name']} 학생의 진단 결과를 분석해보면, 영어 학습에 대한 잠재력은 충분하나 이를 점수로 연결시키는 '정확성'과 '확신'의 균형이 필요한 시점입니다. 총점 {score}점은 단순한 숫자가 아니라, 학생이 그동안 쌓아온 학습의 결과물인 동시에 앞으로 채워나가야 할 학습의 공백을 보여주는 지도입니다.\n\n"
    total_review += f"가장 긍정적인 신호는 전체 문항 중 {master_cnt}개 문항에서 보여준 '실력자'로서의 면모입니다. 이는 학생이 올바른 방향으로 학습했을 때 충분히 성과를 낼 수 있다는 증거입니다. 하지만 경계해야 할 점은 {lucky_cnt}개의 '불안한 잠재력'과 {delusion_cnt}개의 '위험한 착각'입니다. 이 두 영역은 시험 난이도가 조금만 올라가도 바로 등급 하락으로 이어질 수 있는 '시한폭탄'과 같습니다. 따라서 향후 학습 계획은 단순히 진도를 나가는 것이 아니라, 이 '불안한 영역'을 '확실한 영역'으로 바꾸는 데 모든 초점을 맞춰야 합니다.\n\n"
    total_review += "구체적인 솔루션으로는 첫째, '위험한 착각'이 많이 나온 파트를 최우선 순위로 복습해야 합니다. 오답 노트를 작성할 때 단순히 정답만 적는 것이 아니라, 내가 왜 그렇게 생각했는지 사고 과정을 적고 선생님의 교정을 받아야 합니다. 둘째, '불안한 잠재력' 영역은 백지 복습법을 추천합니다. 책을 보지 않고 해당 개념을 설명할 수 있는지 스스로 테스트해보며 메타인지를 높여야 합니다. 셋째, 서술형 문항에서의 감점 요인을 최소화하기 위해 평소 문장 성분을 꼼꼼히 분석하고 영작하는 습관을 들여야 합니다.\n\n"
    total_review += "결론적으로, 이번 진단고사는 학생의 현재 위치를 객관적으로 파악하고, 무의미한 학습 노동을 줄여주는 계기가 될 것입니다. 분석된 데이터를 바탕으로 약점은 보완하고 강점은 극대화하는 스마트한 학습 전략을 실천한다면, 목표하는 등급 달성은 시간문제일 것입니다."

    return grade_text, part_analysis_text, total_review

# ==========================================
# 4. 리포트 UI 컴포넌트
# ==========================================
def show_report_dashboard(df_results, student_name):
    st.markdown(f"## 📊 {student_name}님의 진단 분석 리포트")
    if df_results.empty:
        st.warning("분석할 데이터가 없습니다.")
        return

    # 텍스트 생성
    grade_txt, part_txt, total_txt = generate_verbose_analysis(df_results)

    total_q = len(df_results)
    correct_q = len(df_results[df_results['is_correct'] == True])
    score = int((correct_q / total_q) * 100) if total_q > 0 else 0
    
    # 1. 상단 요약
    c1, c2, c3 = st.columns(3)
    c1.metric("총점", f"{score}점")
    c2.metric("정답 수", f"{correct_q} / {total_q}")
    pred_grade = "1등급" if score >= 90 else "2~3등급" if score >= 70 else "4등급 이하"
    c3.metric("예상 등급", pred_grade)
    
    st.divider()
    
    # 2. 등급 예측 근거
    st.subheader("1. 예상 등급 분석 및 근거")
    st.info(grade_txt)
    
    st.divider()

    # 3. 그래프 (Radar + Pie)
    c_graph1, c_graph2 = st.columns(2)
    
    with c_graph1:
        st.subheader("2. 영역별 역량 분석")
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
        st.caption("▲ 위 그래프는 8개 영역에 대한 학생의 성취도를 시각화한 것입니다. 도형이 넓고 균형 잡힐수록 안정적인 실력을 의미합니다.")
        
    with c_graph2:
        st.subheader("3. 메타인지(확신도) 분석")
        
        # 내부 용어를 한국어 라벨로 매핑
        df_results['quadrant_label'] = df_results['quadrant'].map(QUADRANT_LABELS)
        quad_counts = df_results['quadrant_label'].value_counts()
        
        # 색상 설정
        colors = {
            QUADRANT_LABELS["Master"]: '#28a745',     # 녹색
            QUADRANT_LABELS["Lucky"]: '#ffc107',      # 노랑
            QUADRANT_LABELS["Delusion"]: '#dc3545',   # 빨강
            QUADRANT_LABELS["Deficiency"]: '#6c757d'  # 회색
        }
        
        fig2 = px.pie(names=quad_counts.index, values=quad_counts.values, hole=0.5, 
                     color=quad_counts.index, color_discrete_map=colors)
        st.plotly_chart(fig2, use_container_width=True)
        st.caption("▲ 위 그래프는 정답 여부와 학생의 확신도를 교차 분석한 결과입니다. '실력자' 비율을 높이고 '위험한 착각'을 줄이는 것이 핵심입니다.")

    st.markdown("""
    > **그래프 해석 가이드**
    > * **실력자 (The Ace):** 정답을 맞혔고 확신도 있는 상태. 안정적인 1등급 자산입니다.
    > * **불안한 잠재력 (Anxious Potential):** 맞혔지만 확신이 부족함. 실수할 가능성이 높습니다.
    > * **위험한 착각 (Critical Delusion):** 틀렸는데 맞았다고 착각함. 가장 시급한 교정 대상입니다.
    > * **백지 상태 (Blank Slate):** 모르고 틀림. 기초부터 학습이 필요합니다.
    """)

    st.divider()

    # 4. 파트별 상세 분석
    st.subheader("4. 파트별 정밀 분석")
    st.write(part_txt)
    
    st.divider()
    
    # 5. 총평
    st.subheader("5. 종합 평가 및 솔루션")
    st.success(total_txt)

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
</style>
""", unsafe_allow_html=True)

if 'user_email' not in st.session_state: st.session_state['user_email'] = None
if 'user_name' not in st.session_state: st.session_state['user_name'] = None
if 'current_part' not in st.session_state: st.session_state['current_part'] = 1
if 'view_mode' not in st.session_state: st.session_state['view_mode'] = False

# ---------------------------------------------------------
# 화면 1: 로그인 (이메일 입력)
# ---------------------------------------------------------
if st.session_state['user_email'] is None:
    st.title("🎓 영어 역량 정밀 진단고사")
    st.info("로그인 시 이메일 주소를 사용합니다. (예: student@naver.com)")
    
    tab1, tab2 = st.tabs(["시험 응시 / 이어하기", "내 결과 확인하기"])
    
    with tab1:
        with st.form("login_form"):
            name = st.text_input("이름")
            email = st.text_input("이메일 주소")
            
            # [수정 사항 1] 학교 직접 입력 로직
            school_opt = st.radio("학교", ["신원고등학교", "동산고등학교", "직접 입력"])
            # form 안에서 동적 UI 변경이 제한적이므로, 아래와 같이 처리하거나 
            # form 밖으로 빼야 하지만, 여기서는 조건부 렌더링을 위해 form submit 후 처리보다
            # st.text_input을 항상 보여주되 '직접 입력'일 때만 유효하게 하는 방식이 form 안에서는 안전함.
            # 하지만 Streamlit form 특성상 즉시 반응이 안되므로, 
            # 직관성을 위해 '직접 입력 시 아래 칸에 학교명을 적어주세요'라고 안내하는 것이 좋음.
            custom_school = st.text_input("학교명 (위에서 '직접 입력' 선택 시 작성)")
            
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
    
    st.title(f"Part {part}. {info['title']}")
    st.progress(part / 8)
    
    # [수정 사항 4] Part 8 상단 주의사항
    if part == 8:
        st.error("""
        **[⚠️ 서술형 답안 작성 주의사항]**
        1. 문장의 끝에는 **반드시 마침표(.)**를 찍어야 합니다.
        2. **띄어쓰기**나 줄바꿈 실수는 오답 처리됩니다.
        3. 조건에 맞지 않는 답안은 0점 처리됩니다.
        """)

    with st.form(f"exam_form_{part}"):
        # ------------------------------------
        # TYPE 1: 단순 객관식 (Part 1, 7)
        # ------------------------------------
        if info['type'] == 'simple_obj':
            st.info(f"총 {info['count']}문항입니다.")
            for i in range(1, info['count'] + 1):
                st.markdown(f"**문항 {i}**")
                c1, c2 = st.columns([3, 1])
                with c1: st.radio(f"Q{i} 정답", ["1","2","3","4","5"], horizontal=True, key=f"p{part}_q{i}", label_visibility="collapsed")
                with c2: st.radio(f"확신도", ["확신", "애매", "모름"], horizontal=False, key=f"p{part}_c{i}", label_visibility="collapsed")
                st.markdown("---")

        # ------------------------------------
        # TYPE 2: Part 2
        # ------------------------------------
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

        # ------------------------------------
        # TYPE 3: Part 3
        # ------------------------------------
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

        # ------------------------------------
        # TYPE 4: Part 4
        # ------------------------------------
        elif info['type'] == 'part4_special':
            for i in range(1, 6):
                st.markdown(f"**문항 {i}**")
                if i in [1, 2, 5]: st.text_area(f"Q{i}", key=f"p4_q{i}", height=80)
                else: st.radio(f"Q{i}", ["1","2","3","4","5"], horizontal=True, key=f"p4_q{i}")
                st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key=f"p4_c{i}")
                st.markdown("---")

        # ------------------------------------
        # TYPE 5: Part 5 (순서 정렬 수정됨)
        # ------------------------------------
        elif info['type'] == 'part5_special':
            # [수정 사항 2] 문항 순서를 1, 2, 3, 4, 5 순서로 배치
            for i in range(1, 6):
                st.markdown(f"**문항 {i}**")
                if i in [1, 2, 5]: # 복합형
                    st.radio("(1)", ["1","2","3","4","5"], horizontal=True, key=f"p5_q{i}_obj")
                    st.text_input("(2)", key=f"p5_q{i}_text")
                else: # 3, 4번 단독 서술형
                    st.text_input("정답", key=f"p5_q{i}_text")
                
                st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key=f"p5_c{i}")
                st.markdown("---")

        # ------------------------------------
        # TYPE 6: Part 6
        # ------------------------------------
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

        # ------------------------------------
        # TYPE 8: Part 8
        # ------------------------------------
        elif info['type'] == 'simple_subj':
            for i in range(1, info['count']+1):
                st.markdown(f"**문항 {i}**")
                st.text_area(f"답안", key=f"p{part}_q{i}")
                st.radio("확신도", ["확신", "애매", "모름"], horizontal=True, key=f"p{part}_c{i}")
                st.markdown("---")

        # ==========================================
        # 제출 버튼 및 데이터 처리
        # ==========================================
        if st.form_submit_button(f"Part {part} 제출 및 저장"):
            final_data = []
            is_valid = True # [수정 사항 3] 유효성 검사 플래그
            
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
                for i in range(1, 6):
                    if i in [1, 2, 5]:
                        ao = st.session_state.get(f"p5_q{i}_obj", "")
                        at = st.session_state.get(f"p5_q{i}_text", "")
                        if not (ao and at): is_valid = False
                        final_data.append({'q_id': f"{i}_obj", 'ans': ao, 'conf': st.session_state.get(f"p5_c{i}", "모름")})
                        final_data.append({'q_id': f"{i}_text", 'ans': at, 'conf': st.session_state.get(f"p5_c{i}", "모름")})
                    else:
                        at = st.session_state.get(f"p5_q{i}_text", "")
                        if not at: is_valid = False
                        final_data.append({'q_id': f"{i}_text", 'ans': at, 'conf': st.session_state.get(f"p5_c{i}", "모름")})

            elif info['type'] == 'part6_sets':
                c1 = st.session_state.get("p6_set1_conf", "모름")
                c2 = st.session_state.get("p6_set2_conf", "모름")
                c3 = st.session_state.get("p6_set3_conf", "모름")
                
                # Set 1
                for i in range(1, 5):
                    ans = st.session_state.get(f"p6_q{i}", "")
                    if not ans: is_valid = False
                    final_data.append({'q_id': str(i), 'ans': ans, 'conf': c1})
                # Set 2
                for i in range(5, 9):
                    ans = st.session_state.get(f"p6_q{i}", "")
                    if not ans: is_valid = False
                    final_data.append({'q_id': str(i), 'ans': ans, 'conf': c2})
                # Set 3
                for i in range(9, 13):
                    ans = st.session_state.get(f"p6_q{i}", "")
                    if not ans: is_valid = False
                    final_data.append({'q_id': str(i), 'ans': ans, 'conf': c3})

            # --- [수정 사항 3] 제출 검증 ---
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
