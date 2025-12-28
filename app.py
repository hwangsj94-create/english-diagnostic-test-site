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
# 2. 채점 및 기초 데이터 가공
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

# ==========================================
# 3. 전문가 분석 텍스트 생성기 (Narrative Engine)
# ==========================================

# (1) 예상 등급 분석
def generate_grade_analysis(df_results, student_name):
    part_scores = df_results.groupby('part')['is_correct'].mean() * 100
    all_parts = pd.Series(0, index=range(1, 9))
    part_scores = part_scores.combine_first(all_parts).sort_index()

    score_basic = part_scores[1:3].mean()   # 기초
    score_syntax = part_scores[3:5].mean()  # 구문
    score_logic = part_scores[5:7].mean()   # 논리
    score_killer = part_scores[7:9].mean()  # 킬러

    total_cnt = len(df_results)
    quad_counts = df_results['quadrant'].value_counts()
    delusion_ratio = (quad_counts.get("Delusion", 0) / total_cnt) * 100
    lucky_ratio = (quad_counts.get("Lucky", 0) / total_cnt) * 100

    predicted_grade = ""
    grade_keyword = ""
    
    analysis_text = f"{student_name} 학생의 진단 결과를 바탕으로 분석한 예상 등급과 그에 따른 상세 근거입니다. 현재의 점수는 단순한 숫자가 아니라, 기초 어휘부터 최상위 킬러 문항까지 이어지는 '학습의 위계'가 얼마나 견고한지를 보여주는 지표입니다. 이 분석은 학생이 어떤 파트에서 강점을 보이고 어디에서 병목 현상이 발생하는지를 입체적으로 조명합니다. "

    if score_killer >= 85 and delusion_ratio < 10:
        predicted_grade = "1등급"
        grade_keyword = "완성형 인재 (The Perfectionist)"
        analysis_text += "현재 학생은 안정적인 1등급 구간에 위치해 있습니다. 가장 주목할 점은 변별력을 가르는 Part 7(전략)과 Part 8(서술형 영작)에서 보여준 탁월한 성취도입니다. 이는 단순히 영어를 감으로 푸는 것이 아니라, 출제자의 의도를 꿰뚫고 논리적 함정을 피해가는 디테일이 완성되어 있음을 의미합니다. 또한, 틀린 문제에 대해 섣불리 확신하지 않고 자신의 무지를 인정하는 건전한 메타인지 상태를 유지하고 있어, 학습 효율이 극대화된 상태입니다. 수능 최저 등급 충족은 물론, 내신에서의 1등급 방어도 충분히 가능한 최상의 컨디션입니다. 다만, 1등급을 지키는 것은 달성하는 것보다 어렵습니다. 자만하지 말고 실수를 '0'으로 만드는 훈련을 지속해야 합니다."
    
    elif score_logic >= 80 or score_killer >= 60:
        predicted_grade = "2등급"
        grade_keyword = "불안한 상위권 (The Unstable Top)"
        analysis_text += "전반적으로 우수한 실력을 갖추고 있으나, 1등급의 문턱에서 아쉽게 좌절될 수 있는 '불안한 상위권' 단계입니다. 어휘나 구문 해석 능력은 훌륭하지만, 문장 간의 유기적 연결성을 파악하는 논리 파트(Part 5, 6)나 서술형 조건(Part 8)에서 감점이 발생하고 있습니다. 이는 지문에 있는 객관적 단서보다는 자신의 배경지식이나 감에 의존하여 빈칸을 채우려는 경향이 있음을 시사합니다. 또한 서술형에서 핵심 키워드는 파악했으나 문법적 디테일(태, 시제, 수일치)을 놓치는 경우가 있어, 내신 경쟁에서 치명적인 약점이 될 수 있습니다. 이 '한 끗 차이'를 교정하지 않으면 만년 2등급에 머물게 됩니다."

    elif score_syntax >= 70 or lucky_ratio >= 30:
        predicted_grade = "3등급"
        grade_keyword = "딜레마 구간 (The Keyword Reader)"
        analysis_text += "현재 점수만 보면 중상위권처럼 보일 수 있으나, 속을 들여다보면 위태로운 줄타기를 하고 있는 형국입니다. Part 1, 2의 기초 지식은 있으나, 이를 문장 단위로 엮어내는 '구문 해석력(Part 3)'이 부족합니다. 즉, 문장의 뼈대(주어, 동사)를 정확히 찾지 않고 아는 단어 몇 개를 조합해 소설을 쓰는 식의 '감독해'가 고착화되어 있습니다. 특히 맞힌 문제 중 상당수가 확신 없이 운(Lucky)에 의존한 것으로 나타났는데, 이는 시험 난이도가 조금만 올라가도 점수가 급락할 수 있음을 의미합니다. 지금 당장 점수에 안주하지 않고 문장을 구조적으로 분석하는 눈을 새로 뜨지 않으면, 고학년이 될수록 성적은 계단식으로 하락할 위험이 큽니다."

    elif score_basic >= 60:
        predicted_grade = "4등급"
        grade_keyword = "기초 공사 필요 (Structural Failure)"
        analysis_text += "냉정하게 진단할 때, 단순히 영어 실력이 부족한 것이 아니라 영어를 읽는 것에 대한 심리적 장벽이 존재하는 단계입니다. Part 1 어휘 정답률이 낮아 독해 전략 자체가 무의미하며, Part 3, 4에서는 문장 구조를 전혀 파악하지 못해 해석을 포기하는 경향이 보입니다. 이는 중등 과정의 기초 어휘와 문법 5형식 개념이 제대로 정립되지 않은 채 고등 영어를 접하고 있기 때문입니다. 지금 상태에서 무리하게 고난도 문제를 푸는 것은 밑 빠진 독에 물 붓기와 같습니다. 문제 풀이 스킬보다는 어휘 암기와 구문 기초 공사에 학습 시간의 80% 이상을 쏟아야 하는 '재활 훈련'이 시급합니다."

    else:
        predicted_grade = "5등급 이하"
        grade_keyword = "잠재적 원석 (The Potential)"
        analysis_text += "아직 고등 영어를 소화할 준비가 되지 않은 상태입니다. 전 영역에 걸쳐 정답률이 낮고, 대부분의 문항을 찍거나 확신 없이 풀고 있습니다. 하지만 역설적으로 이는 가장 드라마틱한 성장을 만들 수 있는 기회이기도 합니다. 잘못된 습관이 고착화된 학생보다, 차라리 백지 상태에서 올바른 방법으로 채워 넣는 것이 훨씬 빠른 성장을 가져올 수 있습니다. 지금은 부끄러워할 때가 아니라, 중학교 필수 어휘와 문법부터 다시 시작하는 용기가 필요합니다. 3개월간의 '압축 기초 완성 커리큘럼'을 통해 바닥부터 다시 다진다면, 충분히 상위권으로 도약할 수 있는 잠재력을 가지고 있는 원석입니다."

    return predicted_grade, grade_keyword, analysis_text

# (2) 메타인지 분석 (No headers)
def generate_meta_analysis(df_results, student_name):
    total_cnt = len(df_results)
    if total_cnt == 0: return "데이터 부족"
    
    quad_counts = df_results['quadrant'].value_counts()
    cnt_master = quad_counts.get("Master", 0)
    cnt_delusion = quad_counts.get("Delusion", 0)
    cnt_deficiency = quad_counts.get("Deficiency", 0)
    correct_total = cnt_master + quad_counts.get("Lucky", 0)
    
    score_purity = (cnt_master / correct_total * 100) if correct_total > 0 else 0
    wrong_total = cnt_delusion + cnt_deficiency
    error_resistance = (cnt_delusion / wrong_total * 100) if wrong_total > 0 else 0
    calibration_acc = ((cnt_master + cnt_deficiency) / total_cnt) * 100
    
    text = f"단순히 몇 개를 틀렸는지보다 중요한 것은, 학생이 자신의 지식 상태를 얼마나 정확하게 인지하고 있느냐입니다. {student_name} 학생의 답안 데이터를 '확신도'와 교차 분석하여, 점수의 질적 가치를 평가하는 3가지 핵심 지표를 도출했습니다.\n\n"
    
    text += f"첫째, 학생의 **득점 순도(Score Purity)**는 {int(score_purity)}%입니다. 이는 맞힌 문제 중에서 운이 아니라 진짜 실력으로 맞힌 비율을 뜻합니다. "
    if score_purity < 70: text += "현재 점수에는 상당한 '거품'이 끼어 있습니다. 맞힌 문제라 하더라도 다시 풀면 틀릴 가능성이 높은 '불안한 잠재력' 상태의 문항이 많습니다. 이 점수를 자신의 실력으로 착각하면, 실제 시험에서 점수가 급락하는 낭패를 볼 수 있습니다. "
    else: text += "매우 건강한 수치입니다. 학생이 받은 점수는 요행이 아닌 탄탄한 실력에 기반하고 있어, 어떤 난이도의 시험에서도 쉽게 무너지지 않는 저력을 보여줄 것입니다. "
        
    text += f"\n\n둘째, **오답 고집도(Error Resistance)**는 {int(error_resistance)}%입니다. 이는 틀린 문제 중에서 '몰라서' 틀린 것이 아니라 '맞았다고 착각'한 비율입니다. "
    if error_resistance >= 50: text += "매우 위험한 신호입니다. 학생은 잘못된 개념을 올바른 지식이라고 강하게 믿고 있는 상태입니다. 이런 경우, 일반적인 수업을 들으면 선생님의 설명을 자신의 잘못된 논리에 맞춰 왜곡해서 받아들이게 됩니다. 스스로의 오개념을 깨뜨리는 과정 없이는 성적 향상이 불가능한 '교정 고위험군'입니다. "
    else: text += "양호한 편입니다. 학생은 자신의 부족함을 인정할 줄 아는 열린 태도를 가지고 있어, 올바른 학습법이 제시되면 빠르게 성적을 올릴 수 있는 '학습 스펀지'와 같은 상태입니다. "
        
    text += f"\n\n셋째, **자가 진단 정확도(Calibration Accuracy)**는 {int(calibration_acc)}%입니다. 자신이 아는 것과 모르는 것을 구별하는 능력입니다. 이 능력이 높을수록 아는 것은 건너뛰고 모르는 것에 집중하는 효율적인 학습이 가능합니다. 낮은 경우에는 아는 것을 또 보거나 모르는 것을 안다고 착각하여 시간을 낭비하게 됩니다.\n\n"
    
    text += "결론적으로, 점수 뒤에 숨겨진 이 메타인지 패턴을 이해해야 합니다. 모르는 건 죄가 아니지만, '안다고 착각하는 것'은 입시에서 가장 큰 적입니다. 이번 진단은 이 '착각'을 수치화하여 보여주었다는 점에서 큰 의미가 있습니다."
    return text

# (3) Part 종합 총평 (No headers)
def generate_part_overview(df_results, student_name):
    part_scores = df_results.groupby('part')['is_correct'].mean() * 100
    all_parts = pd.Series(0, index=range(1, 9))
    part_scores = part_scores.combine_first(all_parts).sort_index()
    
    score_fund = part_scores[1:3].mean() # 기초
    score_logic = part_scores[3:7].mean() # 논리/독해
    score_killer = part_scores[7:9].mean() # 실전/응용
    
    text = f"학생의 8개 파트 성취도를 '기초 체력', '독해 논리력', '실전 응용력'이라는 3대 핵심 역량으로 재구성하여 분석했습니다. 이 분석은 학생이 점수를 얻는 방식과 잃는 방식의 패턴을 명확하게 보여줍니다.\n\n"
    
    text += f"첫째, 어휘와 어법을 포함한 **'기초 체력' 영역**은 {int(score_fund)}점입니다. "
    if score_fund >= 80: text += "이는 영어를 학습할 수 있는 기본적인 재료가 아주 훌륭하게 갖춰져 있음을 의미합니다. 단어 암기나 문법 개념 이해에 있어 성실함이 돋보이며, 이를 바탕으로 상위 단계로 나아갈 준비가 되어 있습니다. "
    else: text += "건물을 지을 벽돌과 시멘트가 부족한 상태입니다. 어휘량이 부족하면 아무리 좋은 독해 스킬을 배워도 적용할 수 없습니다. 매일 꾸준한 단어 암기와 문법 개념 정리가 선행되지 않으면 이후 학습은 사상누각이 될 것입니다. "
        
    text += f"\n\n둘째, 문장을 해석하고 글의 맥락을 파악하는 **'독해 논리력' 영역**은 {int(score_logic)}점입니다. "
    if score_logic >= 80: text += "문장 구조를 보는 눈이 정확하고, 글의 전개 방식을 파악하는 논리적 사고력이 뛰어납니다. 단순히 번역하는 수준을 넘어 필자의 의도를 파악하는 '진짜 독해'를 하고 있습니다. "
    elif score_logic >= 60: text += "해석은 어느 정도 되지만, 글 전체를 관통하는 주제를 찾거나 문장 간의 연결 고리를 찾는 데 어려움을 겪고 있습니다. 이는 나무만 보고 숲을 보지 못하는 독해 습관 때문입니다. "
    else: text += "문장을 만났을 때 구조적으로 분석하지 못하고 당황하는 경향이 큽니다. 감에 의존한 찍기식 독해를 하고 있어, 지문의 난이도에 따라 점수 편차가 매우 클 것으로 예상됩니다. "
        
    text += f"\n\n셋째, 고난도 문제 해결과 영작을 포함한 **'실전 응용력' 영역**은 {int(score_killer)}점입니다. "
    if score_killer >= 80: text += "1등급을 결정짓는 킬러 문항에 대한 방어력이 상당합니다. 특히 서술형 조건이나 함정 문제에서도 흔들리지 않는 디테일은 학생의 가장 큰 무기입니다. "
    else: text += "앞선 단계가 잘 되어있더라도, 결국 점수를 깎아먹는 것은 이 구간입니다. 시간 관리 부족이나 서술형에서의 사소한 실수들이 등급 하락의 주원인이 되고 있습니다. 실전과 같은 환경에서의 훈련이 필요합니다."
        
    text += "\n\n종합적으로 볼 때, 학생은 특정 영역의 강점을 살리기보다 무너진 균형을 맞추는 것이 급선무입니다. 위 그래프에서 가장 낮게 나타난 막대그래프가 바로 학생의 '성적 발목'을 잡고 있는 구간임을 인지하고, 해당 영역에 학습 에너지를 집중해야 합니다."
    return text

# (4) 파트별 상세 (Flow Narrative, >300 chars)
def generate_part_specific_analysis(df_results, student_name):
    part_stats = {}
    for p in range(1, 9):
        p_df = df_results[df_results['part'] == p]
        if p_df.empty:
            part_stats[p] = {'score': 0, 'master': 0, 'lucky': 0, 'delusion': 0}
            continue
        total = len(p_df)
        quads = p_df['quadrant'].value_counts()
        part_stats[p] = {
            'score': int(p_df['is_correct'].mean() * 100),
            'master': (quads.get("Master", 0) / total) * 100,
            'lucky': (quads.get("Lucky", 0) / total) * 100,
            'delusion': (quads.get("Delusion", 0) / total) * 100
        }

    # 파트별 특성과 학생의 상태를 결합하여 풍성한 텍스트 생성
    detail_analysis_dict = {}
    
    # Context Data
    part_context = {
        1: {"def": "단어의 표면적 의미를 넘어 문맥 속에서 활용되는 뉘앙스까지 파악하는 능력", "risk": "다의어 및 파생어 해석 불가", "sol": "예문 중심의 Context 학습"},
        2: {"def": "문장의 구조를 결정짓는 규칙을 이해하고 이를 실전 문제에 적용하는 능력", "risk": "감에 의존한 문제 풀이 및 서술형 감점", "sol": "정답의 근거를 설명하는 티칭 훈련"},
        3: {"def": "문장의 주성분(주어/동사)과 수식어구를 정확히 구분하여 뼈대를 파악하는 능력", "risk": "고난도 만연체 문장에서의 오독 발생", "sol": "문장 성분 표시 및 청킹(Chunking) 훈련"},
        4: {"def": "번역된 텍스트의 이면적 의미를 추론하고 글의 핵심 요지를 파악하는 사고력", "risk": "빈칸 추론 등 추상적 지문 해결 불가", "sol": "한 문장 요약 및 사고 구체화 훈련"},
        5: {"def": "접속사와 지시어를 단서로 문장 간의 논리적 연결 관계를 추적하는 능력", "risk": "순서 배열 및 문장 삽입 유형 오답", "sol": "논리적 연결 고리(Signal Word) 도식화"},
        6: {"def": "지엽적인 정보에 매몰되지 않고 글 전체의 전개 방식과 주제를 조망하는 능력", "risk": "시간 부족 및 주제 파악 실패", "sol": "첫/마지막 문장을 통한 거시적 독해 훈련"},
        7: {"def": "문제 유형별 출제 의도를 간파하고 효율적으로 정보를 찾아내는 전략적 능력", "risk": "비효율적 풀이로 인한 시간 관리 실패", "sol": "Scanning & Skimming 전략 체화"},
        8: {"def": "문법적 제약 조건을 준수하며 자신의 생각을 영어 문장으로 정확히 출력하는 능력", "risk": "내신 등급을 가르는 결정적 감점 요인", "sol": "자가 첨삭 및 마이크로 디테일 교정"}
    }

    for p in range(1, 9):
        stat = part_stats[p]
        ctx = part_context[p]
        
        # 1. 현상 진단 (Status)
        text = f"{EXAM_STRUCTURE[p]['title']} 영역은 {ctx['def']}입니다. 이 영역에서 {student_name} 학생은 {stat['score']}점의 성취도를 보였습니다. "
        
        if stat['score'] >= 80:
            text += "이는 해당 파트의 핵심 개념이 매우 견고하게 자리 잡혀 있음을 의미합니다. 실전 문제에서도 당황하지 않고 출제자의 의도를 파악해내는 모습이 인상적입니다. "
            if stat['lucky'] >= 30:
                text += "다만, 데이터를 상세 분석해 보면 맞힌 문제 중 상당수가 확신 없이 '감'으로 선택된 것으로 나타납니다. 운도 실력의 일부일 수 있으나, 난이도가 급격히 상승하는 시험장에서는 이러한 불안 요소가 등급 하락의 원인이 될 수 있음을 경계해야 합니다. "
            elif stat['delusion'] >= 20:
                text += "하지만 옥에 티처럼, 틀린 소수의 문제에 대해 '맞았다'고 확신하는 경향이 발견되었습니다. 이는 사소한 개념의 오해가 있음을 시사하므로, 최상위권 도약을 위해 반드시 짚고 넘어가야 할 부분입니다. "
            else:
                text += "특히 자신의 정답에 대해 확신을 가지고 있는 비율이 높아, 이 영역은 앞으로도 학생의 성적을 지탱해 줄 든든한 전략 과목이 될 것입니다. "
        
        elif stat['score'] >= 60:
            text += "평균적인 이해도를 보이고 있으나, 고득점을 위한 확실한 무기가 되기에는 다소 부족한 상태입니다. 기본적인 문제는 해결하지만 복합적인 사고를 요하거나 함정이 있는 문제에서 흔들리는 경향이 있습니다. "
            if stat['delusion'] >= 30:
                text += "특히 우려스러운 점은 틀린 문제의 30% 이상을 정답이라고 확신했다는 것입니다. 이는 단순 실수가 아니라 잘못된 개념이 고착화되어 있음을 의미하며, 방치할 경우 '열심히 공부해도 점수가 오르지 않는' 정체기의 주범이 될 수 있습니다. "
            else:
                text += "아직 해당 영역에 대한 자신감이 부족하여 과감하게 답을 선택하지 못하고 망설이는 모습이 역력합니다. 반복적인 훈련을 통해 개념을 체화하는 과정이 필요합니다. "
        
        else: # 점수 낮음
            text += "현재 기초 학습이 시급한 상태로, 해당 영역에 대한 심리적 장벽마저 느껴집니다. 문제 접근 방식 자체를 찾지 못해 풀이를 포기하거나 찍는 비율이 높습니다. "
            text += "이는 단순히 공부량이 부족해서라기보다, 이 단계로 넘어가기 위한 이전 단계의 선수 지식(어휘 등)이 부족하여 발생한 도미노 현상일 가능성이 높습니다. "

        # 2. 원인 및 위험성 (Cause & Risk) - 줄글로 연결
        text += "이러한 결과가 나타난 근본적인 원인을 살펴보면, 단순히 영어를 못해서가 아니라 학습의 방향성에 교정이 필요함을 알 수 있습니다. "
        if p == 3:
            text += "문장의 뼈대를 보지 않고 아는 단어만으로 의미를 조합하는 습관이 남아있어, 문장이 길어지면 해석의 정확도가 급격히 떨어지는 것입니다. 이대로라면 고학년 지문에서 오독이 발생할 확률이 매우 높습니다. "
        elif p == 8:
            text += "머릿속으로 아는 것과 손으로 써내는 것의 괴리를 좁히지 못하고 있습니다. 수일치나 태와 같은 문법적 디테일에서 감점이 누적되면, 결국 내신 등급 경쟁에서 밀려날 수밖에 없습니다. "
        else:
            text += f"정답을 맞히는 것에만 급급하여, 문제 속에 숨겨진 논리적 단서들을 놓치고 있기 때문입니다. {ctx['risk']}와 같은 위험성이 존재하므로, 지금 바로잡지 않으면 고질적인 약점이 될 수 있습니다. "

        # 3. 처방 (Solution) - 줄글로 마무리
        text += f"따라서 향후 학습은 양보다는 질에 집중해야 합니다. {ctx['sol']}을 최우선 과제로 삼아, 단순히 문제를 많이 푸는 것이 아니라 한 문제를 풀더라도 그 근거를 명확히 설명할 수 있을 때까지 파고드는 집요함이 필요합니다."

        detail_analysis_dict[p] = text

    return detail_analysis_dict

# (5) 종합 평가 및 솔루션 (Narrative + No Headers + Clinic Separation)
def generate_total_review(df_results, student_name):
    part_scores = df_results.groupby('part')['is_correct'].mean() * 100
    all_parts = pd.Series(0, index=range(1, 9))
    part_scores = part_scores.combine_first(all_parts).sort_index()
    
    sorted_parts = part_scores.sort_values(ascending=True)
    weak_parts_indices = sorted_parts.index[:2].tolist()
    
    weak_titles = [f"**{EXAM_STRUCTURE[p]['title'].split('.')[1].strip()}**" for p in weak_parts_indices]
    avg_weak_score = int(sorted_parts.iloc[:2].mean())

    # 1. 진단 요약
    summary = f"이번 진단고사 데이터를 정밀 분석한 결과, {student_name} 학생의 성적 향상을 위해 가장 시급하게 보완해야 할 '병목 구간'은 {', '.join(weak_titles)} 영역인 것으로 나타났습니다. "
    summary += f"해당 취약 영역들의 평균 정답률은 약 {avg_weak_score}%에 불과하여, 전체적인 영어 실력의 균형을 무너뜨리는 주원인이 되고 있습니다. "
    
    delusion_cnt = 0
    for p in weak_parts_indices:
        delusion_cnt += df_results[df_results['part'] == p]['quadrant'].value_counts().get("Delusion", 0)
        
    if delusion_cnt > 0:
        summary += f"특히 해당 파트에서 오답임에도 정답이라고 확신한 문항이 발견되었습니다. 이는 단순 실수가 아니라 개념의 오류가 뿌리 깊게 박혀 있음을 시사합니다. "
    else:
        summary += f"해당 파트에 대한 기초 개념 자체가 정립되지 않아 문제 접근 자체에 어려움을 겪고 있는 상태입니다. "
    
    summary += "이러한 불균형을 해소하지 않고 무작정 진도만 나가는 것은 밑 빠진 독에 물을 붓는 것과 같습니다. 따라서 향후 학습 계획은 전면적인 재조정이 필요합니다.\n\n"

    # 2. 우선순위 로드맵 (Narrative)
    summary += f"성적 상승을 위해 가장 먼저 집중해야 할 우선순위 과제는 다음과 같습니다. "
    
    roadmap_sentences = []
    for i, p in enumerate(weak_parts_indices):
        title = EXAM_STRUCTURE[p]['title'].split('.')[1].strip()
        order = "첫째" if i == 0 else "둘째"
        
        if p in [1, 2]:
            roadmap_sentences.append(f"{order}, **{title}** 영역의 경우 건물의 기초를 다지듯 중등/고등 필수 개념의 완전 학습을 목표로 해야 합니다. 문제 풀이보다는 개념 암기와 예문 학습 비중을 대폭 늘려 뿌리부터 튼튼하게 만들어야 합니다.")
        elif p in [3, 4]:
            roadmap_sentences.append(f"{order}, **{title}** 영역은 감으로 읽는 습관을 버리고 문장 성분을 쪼개는 구조 독해력을 확보해야 합니다. 모든 문장의 주어와 동사를 표시하고 끊어 읽는 정독 훈련을 통해 해석의 정확도를 높여야 합니다.")
        elif p in [5, 6]:
            roadmap_sentences.append(f"{order}, **{title}** 영역은 글의 전개 방식을 파악하여 정답의 논리적 근거를 찾는 연습이 필요합니다. 접속사와 지시어를 단서로 문장 간의 관계를 도식화하며 읽어야 합니다.")
        else:
            roadmap_sentences.append(f"{order}, **{title}** 영역은 실전 감각 극대화 및 서술형 감점 요인을 제거하는 디테일 훈련이 필수입니다. 시간 제한을 둔 풀이와 영작 후 자가 첨삭 훈련을 반복해야 합니다.")
    
    summary += " ".join(roadmap_sentences) + "\n\n"

    # 3. 학원의 솔루션 (정규/클리닉 분리)
    summary += f"저희 대세 영어학원은 이러한 약점을 보완하기 위해 이원화된 솔루션을 제공합니다. "
    
    # 정규 수업
    class_action = "우선 **[정규 수업]**에서는 "
    if any(p in [1, 2] for p in weak_parts_indices):
        class_action += "매 수업 엄격한 어휘/어법 테스트를 통해 개념 숙지 여부를 점검하고, "
    if any(p in [3, 4] for p in weak_parts_indices):
        class_action += "강사와 함께 문장을 분석하는 '구문 독해 시뮬레이션'을 집중적으로 훈련하며, "
    if any(p in [5, 6] for p in weak_parts_indices):
        class_action += "지문의 구조를 분석하고 정답의 근거를 찾는 훈련을 실시하며, "
    if any(p in [7, 8] for p in weak_parts_indices):
        class_action += "실전 모의고사와 킬러 문항 공략을 통해 실전 감각을 극대화합니다. "
    summary += class_action + "\n\n"
    
    # 클리닉
    summary += "또한, 정규 수업에서 다루기 힘든 개인별 약점은 **[Clinic]** 시간을 통해 해결합니다. "
    clinic_needs = []
    if any(p in [1,2] for p in weak_parts_indices): clinic_needs.append("미통과된 단어/개념 재시험")
    if any(p in [3,4] for p in weak_parts_indices): clinic_needs.append("개별 구문 분석 첨삭")
    if any(p in [7,8] for p in weak_parts_indices): clinic_needs.append("1:1 서술형 답안 교정")
    
    if clinic_needs:
        summary += f"특히 학생에게 필요한 **{', '.join(clinic_needs)}**을 1:1로 밀착 지도하여 오개념을 끝까지 추적하고 교정하겠습니다. "
    else:
        summary += "학생이 이해하지 못한 부분을 1:1로 질문받고, 오개념이 교정될 때까지 끝까지 확인하겠습니다. "

    # 4. 필수 결론 멘트
    summary += "\n\n정밀한 진단은 모두 끝났습니다. 이제 남은 것은 처방전입니다. 대세 영어학원 지축 캠퍼스에서 황성진, 김찬종 두 명의 원장이 직접 책임지겠습니다. 다시 돌아오지 않는 이 시간, 우리 아이에게 가장 필요한 학습으로 지도할 것을 약속 드립니다."

    return summary

# ==========================================
# 4. 리포트 UI
# ==========================================
def show_report_dashboard(df_results, student_name):
    st.markdown("""<script>function printPage() {window.print();}</script>""", unsafe_allow_html=True)
    st.markdown(f"## 📊 {student_name}님의 영어 역량 정밀 진단 리포트")
    
    if df_results.empty:
        st.warning("분석할 데이터가 없습니다.")
        return

    pred_grade, grade_kw, grade_txt = generate_grade_analysis(df_results, student_name)
    meta_txt = generate_meta_analysis(df_results, student_name)
    part_overview_txt = generate_part_overview(df_results, student_name)
    det_dict = generate_part_specific_analysis(df_results, student_name)
    total_txt = generate_total_review(df_results, student_name)
    
    total_q = len(df_results)
    correct_q = len(df_results[df_results['is_correct'] == True])
    score = int((correct_q / total_q) * 100) if total_q > 0 else 0
    
    # Header
    c1, c2, c3, c4 = st.columns([2, 2, 3, 2])
    c1.metric("종합 점수", f"{score}점 / 100점")
    c2.metric("맞힌 문제/전체 문제", f"{correct_q}/{total_q}")
    c3.metric("예상 등급", f"{pred_grade} ({grade_kw.split('(')[0]})")
    with c4:
        st.button("🖨️ PDF로 저장", on_click=None, type="primary", key="print_btn")
        if st.session_state.get("print_btn"):
            st.components.v1.html("<script>window.print();</script>", height=0, width=0)
    st.divider()
    
    # 1. 등급 분석
    st.subheader("1. 예상 등급 분석 및 근거")
    st.write(grade_txt)
    st.divider()

    # 2. 메타인지 분석 (순서 2번)
    c_m1, c_m2 = st.columns([1, 1])
    with c_m1:
        st.subheader("2. 메타인지(확신도) 분석")
        df_results['quadrant_label'] = df_results['quadrant'].map(QUADRANT_LABELS)
        quad_counts = df_results['quadrant_label'].value_counts()
        colors = {QUADRANT_LABELS["Master"]: '#28a745', QUADRANT_LABELS["Lucky"]: '#ffc107', 
                  QUADRANT_LABELS["Delusion"]: '#dc3545', QUADRANT_LABELS["Deficiency"]: '#6c757d'}
        fig_pie = px.pie(names=quad_counts.index, values=quad_counts.values, hole=0.4, color=quad_counts.index, color_discrete_map=colors)
        st.plotly_chart(fig_pie, use_container_width=True)
    with c_m2:
        st.write("\n")
        st.write(meta_txt)
    st.divider()

    # 3. Part 종합 총평 (순서 3번)
    c_g1, c_g2 = st.columns([1, 1])
    with c_g1:
        st.subheader("3. Part 종합 총평")
        part_stats = df_results.groupby('part')['is_correct'].mean() * 100
        all_parts = pd.Series(0, index=range(1, 9))
        part_stats = part_stats.combine_first(all_parts).sort_index()
        df_bar = pd.DataFrame({
            '영역': [EXAM_STRUCTURE[p]['title'].split('.')[1].strip() for p in range(1,9)],
            '점수': part_stats.values
        })
        fig_bar = px.bar(df_bar, x='영역', y='점수', text='점수', color='점수', color_continuous_scale='Blues', range_y=[0,100])
        fig_bar.update_traces(texttemplate='%{text:.0f}점', textposition='outside')
        st.plotly_chart(fig_bar, use_container_width=True)
    with c_g2:
        st.write("\n")
        st.write(part_overview_txt)
    st.divider()
    
    # 4. 파트별 상세
    st.subheader("4. 파트별 정밀 분석")
    for p in range(1, 9):
        with st.expander(f"{EXAM_STRUCTURE[p]['title']}", expanded=False):
            st.write(det_dict[p])
    st.divider()
    
    # 5. 총평
    st.subheader("5. 종합 평가 및 솔루션")
    st.write(total_txt)

# ==========================================
# 5. 메인 앱 실행
# ==========================================
st.set_page_config(page_title="영어 역량 정밀 진단", layout="wide")
st.markdown("""<style>
div.row-widget.stRadio > div {flex-direction: row;} 
div.row-widget.stRadio > div > label {background-color: #f8f9fa; padding: 10px 20px; border-radius: 8px; margin-right: 8px; cursor: pointer; border: 1px solid #dee2e6;}
div.row-widget.stRadio > div > label:hover {background-color: #e9ecef;}
textarea {font-size: 16px !important;} input[type="text"] {font-size: 16px !important;}
@media print { button { display: none !important; } .stApp { margin: 0; padding: 0; } }
</style>""", unsafe_allow_html=True)

if 'user_email' not in st.session_state: st.session_state['user_email'] = None
if 'user_name' not in st.session_state: st.session_state['user_name'] = None
if 'current_part' not in st.session_state: st.session_state['current_part'] = 1
if 'view_mode' not in st.session_state: st.session_state['view_mode'] = False

if st.session_state['user_email'] is None:
    st.title("🎓 영어 역량 정밀 진단고사")
    st.info("로그인 시 이메일 주소를 사용합니다.")
    tab1, tab2 = st.tabs(["시험 응시", "결과 확인"])
    with tab1:
        with st.form("login"):
            name = st.text_input("이름")
            email = st.text_input("이메일")
            c_s1, c_s2 = st.columns(2)
            with c_s1: s_opt = st.radio("학교", ["신원고등학교", "동산고등학교", "직접 입력"])
            with c_s2: c_sch = st.text_input("학교명 (직접 입력 시)")
            grade = st.selectbox("학년", ["중3", "고1", "고2", "고3"])
            if st.form_submit_button("시작하기"):
                if name and email and "@" in email:
                    sch = c_sch if s_opt == "직접 입력" else s_opt
                    stu = get_student(name, email)
                    if stu: st.session_state['current_part'] = 9 if stu['last_part']>8 else stu['last_part']
                    else: save_student(name, email, sch, grade)
                    st.session_state['user_name'] = name; st.session_state['user_email'] = email; st.rerun()
                else: st.error("정보를 정확히 입력하세요.")
    with tab2:
        with st.form("check"):
            n = st.text_input("이름"); e = st.text_input("이메일")
            if st.form_submit_button("조회"):
                if get_student(n, e):
                    st.session_state['user_name'] = n; st.session_state['user_email'] = e; st.session_state['view_mode'] = True; st.rerun()
                else: st.error("이력이 없습니다.")

elif not st.session_state['view_mode'] and st.session_state['current_part'] <= 8:
    part = st.session_state['current_part']
    info = EXAM_STRUCTURE[part]
    st.title(info['title']); st.progress(part/8)
    if part == 8: st.error("⚠️ 서술형 주의: 마침표(.) 필수, 띄어쓰기 주의")
    
    with st.form(f"exam_{part}"):
        if info['type'] == 'simple_obj':
            for i in range(1, info['count']+1):
                st.markdown(f"**문항 {i}**")
                c1, c2 = st.columns([3,1])
                with c1: st.radio(f"Q{i}", ["1","2","3","4","5"], horizontal=True, key=f"p{part}_q{i}", label_visibility="collapsed")
                with c2: st.radio("확신도", ["확신","애매","모름"], key=f"p{part}_c{i}", label_visibility="collapsed")
                st.markdown("---")
        elif info['type'] == 'part2_special':
            for i in range(1, 10):
                st.markdown(f"**문항 {i}**"); c1, c2 = st.columns([3,1])
                with c1: st.radio(f"Q{i}", ["1","2","3","4","5"], horizontal=True, key=f"p2_q{i}", label_visibility="collapsed")
                with c2: st.radio("확신도", ["확신","애매","모름"], key=f"p2_c{i}")
                st.markdown("---")
            st.markdown("**문항 10**"); c1,c2,c3 = st.columns([2,2,1])
            with c1: st.text_input("틀린단어", key="p2_q10_wrong")
            with c2: st.text_input("고친단어", key="p2_q10_correct")
            with c3: st.radio("확신도", ["확신","애매","모름"], key="p2_c10")
        elif info['type'] == 'part3_special':
            st.markdown("**문항 1**"); c1,c2=st.columns(2)
            with c1: st.text_input("Main Subject", key="p3_q1_subj")
            with c2: st.text_input("Main Verb", key="p3_q1_verb")
            st.radio("정답", ["1","2","3","4","5"], horizontal=True, key="p3_q1_obj"); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key="p3_c1"); st.markdown("---")
            st.markdown("**문항 2**"); c1,c2=st.columns(2)
            with c1: st.text_input("Main Subject", key="p3_q2_subj")
            with c2: st.text_input("Main Verb", key="p3_q2_verb")
            st.radio("정답", ["1","2","3","4","5"], horizontal=True, key="p3_q2_obj"); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key="p3_c2"); st.markdown("---")
            st.markdown("**문항 3**"); st.text_input("Subject", key="p3_q3_subj")
            st.radio("정답", ["1","2","3","4","5"], horizontal=True, key="p3_q3_obj"); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key="p3_c3"); st.markdown("---")
            st.markdown("**문항 4**"); c1,c2=st.columns(2)
            with c1: st.text_input("Main Subject", key="p3_q4_subj")
            with c2: st.text_input("Main Verb", key="p3_q4_verb")
            st.radio("정답", ["1","2","3","4","5"], horizontal=True, key="p3_q4_obj"); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key="p3_c4"); st.markdown("---")
            st.markdown("**문항 5**"); st.radio("정답", ["1","2","3","4","5"], horizontal=True, key="p3_q5_obj")
            st.text_input("빈칸", key="p3_q5_text"); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key="p3_c5"); st.markdown("---")
        elif info['type'] == 'part4_special':
            for i in range(1,6):
                st.markdown(f"**문항 {i}**")
                if i in [1,2,5]: st.text_area("답안", key=f"p4_q{i}", height=80)
                else: st.radio("정답", ["1","2","3","4","5"], horizontal=True, key=f"p4_q{i}")
                st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=f"p4_c{i}"); st.markdown("---")
        elif info['type'] == 'part5_special':
            for i in [1,2]: st.markdown(f"**문항 {i}**"); st.radio("(1)", ["1","2","3","4","5"], horizontal=True, key=f"p5_q{i}_obj"); st.text_input("(2)", key=f"p5_q{i}_text"); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=f"p5_c{i}"); st.markdown("---")
            for i in [3,4]: st.markdown(f"**문항 {i}**"); st.text_input("정답", key=f"p5_q{i}_text"); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=f"p5_c{i}"); st.markdown("---")
            st.markdown("**문항 5**"); st.radio("(1)", ["1","2","3","4","5"], horizontal=True, key=f"p5_q5_obj"); st.text_input("(2)", key=f"p5_q5_text"); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=f"p5_c5"); st.markdown("---")
        elif info['type'] == 'part6_sets':
            qg=1
            for s in range(1,4):
                st.markdown(f"### [Set {s}]"); st.text_input(f"Q{qg} Kw", key=f"p6_q{qg}"); qg+=1
                st.radio(f"Q{qg} Tone", ["1","2","3","4","5"], horizontal=True, key=f"p6_q{qg}"); qg+=1
                st.radio(f"Q{qg} Flow", ["1","2","3","4"], horizontal=True, key=f"p6_q{qg}"); qg+=1
                st.text_area(f"Q{qg} Sum", key=f"p6_q{qg}"); qg+=1
                st.radio(f"Set {s} 확신도", ["확신","애매","모름"], horizontal=True, key=f"p6_set{s}_conf"); st.markdown("---")
        elif info['type'] == 'simple_subj':
            for i in range(1,6): st.markdown(f"**문항 {i}**"); st.text_area("답안", key=f"p8_q{i}"); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=f"p8_c{i}"); st.markdown("---")

        if st.form_submit_button("제출 및 저장"):
            final_data = []
            is_valid = True
            
            if info['type'] in ['simple_obj', 'simple_subj']:
                for i in range(1, info['count']+1):
                    a = st.session_state.get(f"p{part}_q{i}",""); c = st.session_state.get(f"p{part}_c{i}","모름")
                    if not a: is_valid = False
                    final_data.append({'q_id':str(i), 'ans':a, 'conf':c})
            elif info['type'] == 'part2_special':
                for i in range(1,10):
                    a = st.session_state.get(f"p2_q{i}",""); c = st.session_state.get(f"p2_c{i}","모름")
                    if not a: is_valid = False
                    final_data.append({'q_id':str(i), 'ans':a, 'conf':c})
                w = st.session_state.get("p2_q10_wrong",""); o = st.session_state.get("p2_q10_correct",""); c = st.session_state.get("p2_c10","모름")
                if not w or not o: is_valid = False
                final_data.append({'q_id':'10_wrong','ans':w,'conf':c}); final_data.append({'q_id':'10_correct','ans':o,'conf':c})
            elif info['type'] == 'part3_special':
                s1=st.session_state.get("p3_q1_subj",""); v1=st.session_state.get("p3_q1_verb",""); o1=st.session_state.get("p3_q1_obj",""); c1=st.session_state.get("p3_c1","모름")
                if not(s1 and v1 and o1): is_valid=False
                final_data.extend([{'q_id':'1_subj','ans':s1,'conf':c1},{'q_id':'1_verb','ans':v1,'conf':c1},{'q_id':'1_obj','ans':o1,'conf':c1}])
                s2=st.session_state.get("p3_q2_subj",""); v2=st.session_state.get("p3_q2_verb",""); o2=st.session_state.get("p3_q2_obj",""); c2=st.session_state.get("p3_c2","모름")
                if not(s2 and v2 and o2): is_valid=False
                final_data.extend([{'q_id':'2_subj','ans':s2,'conf':c2},{'q_id':'2_verb','ans':v2,'conf':c2},{'q_id':'2_obj','ans':o2,'conf':c2}])
                s3=st.session_state.get("p3_q3_subj",""); o3=st.session_state.get("p3_q3_obj",""); c3=st.session_state.get("p3_c3","모름")
                if not(s3 and o3): is_valid=False
                final_data.extend([{'q_id':'3_subj','ans':s3,'conf':c3},{'q_id':'3_obj','ans':o3,'conf':c3}])
                s4=st.session_state.get("p3_q4_subj",""); v4=st.session_state.get("p3_q4_verb",""); o4=st.session_state.get("p3_q4_obj",""); c4=st.session_state.get("p3_c4","모름")
                if not(s4 and v4 and o4): is_valid=False
                final_data.extend([{'q_id':'4_subj','ans':s4,'conf':c4},{'q_id':'4_verb','ans':v4,'conf':c4},{'q_id':'4_obj','ans':o4,'conf':c4}])
                o5=st.session_state.get("p3_q5_obj",""); t5=st.session_state.get("p3_q5_text",""); c5=st.session_state.get("p3_c5","모름")
                if not(o5 and t5): is_valid=False
                final_data.extend([{'q_id':'5_obj','ans':o5,'conf':c5},{'q_id':'5_text','ans':t5,'conf':c5}])
            elif info['type'] == 'part4_special':
                for i in range(1,6):
                    a=st.session_state.get(f"p4_q{i}",""); c=st.session_state.get(f"p4_c{i}","모름")
                    if not a: is_valid=False
                    final_data.append({'q_id':str(i),'ans':a,'conf':c})
            elif info['type'] == 'part5_special':
                for i in [1,2,5]:
                    ao=st.session_state.get(f"p5_q{i if i!=5 else 5}_obj",""); at=st.session_state.get(f"p5_q{i if i!=5 else 5}_text",""); c=st.session_state.get(f"p5_c{i if i!=5 else 5}","모름")
                    if not(ao and at): is_valid=False
                    final_data.append({'q_id':f"{i}_obj",'ans':ao,'conf':c}); final_data.append({'q_id':f"{i}_text",'ans':at,'conf':c})
                for i in [3,4]:
                    at=st.session_state.get(f"p5_q{i}_text",""); c=st.session_state.get(f"p5_c{i}","모름")
                    if not at: is_valid=False
                    final_data.append({'q_id':f"{i}_text",'ans':at,'conf':c})
            elif info['type'] == 'part6_sets':
                c1=st.session_state.get("p6_set1_conf","모름"); c2=st.session_state.get("p6_set2_conf","모름"); c3=st.session_state.get("p6_set3_conf","모름")
                for i in range(1,5):
                    a=st.session_state.get(f"p6_q{i}",""); 
                    if not a: is_valid=False
                    final_data.append({'q_id':str(i),'ans':a,'conf':c1})
                for i in range(5,9):
                    a=st.session_state.get(f"p6_q{i}",""); 
                    if not a: is_valid=False
                    final_data.append({'q_id':str(i),'ans':a,'conf':c2})
                for i in range(9,13):
                    a=st.session_state.get(f"p6_q{i}",""); 
                    if not a: is_valid=False
                    final_data.append({'q_id':str(i),'ans':a,'conf':c3})

            if not is_valid:
                st.error("⚠️ 모든 문항의 정답을 입력해야 제출할 수 있습니다.")
            else:
                try:
                    with st.spinner("저장 중..."):
                        save_answers_bulk(st.session_state['user_email'], part, final_data)
                        st.session_state['current_part'] += 1
                        time.sleep(1)
                        st.rerun()
                except Exception as e: st.error(f"오류: {e}")

else:
    st.balloons()
    try:
        df_res = calculate_results(st.session_state['user_email'])
        show_report_dashboard(df_res, st.session_state['user_name'])
    except Exception as e: st.error(f"분석 중 오류 발생: {e}")
    if st.button("처음으로"): st.session_state.clear(); st.rerun()
