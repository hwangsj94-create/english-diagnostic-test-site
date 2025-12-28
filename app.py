import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.graph_objects as go
import plotly.express as px
import time
import random

# ==========================================
# [설정] 파트별 문항 상세 구성 및 등급 기준
# ==========================================
EXAM_STRUCTURE = {
    1: {"title": "Part 1. 어휘력 (Vocabulary)", "type": "simple_obj", "count": 30, "intent": "단순 암기가 아닌 문맥 속 의미 파악과 유의어/반의어 활용 능력"},
    2: {"title": "Part 2. 어법 지식 (Grammar)", "type": "part2_special", "count": 10, "intent": "단순 실수와 개념 부재를 구별하고, 조건에 맞는 문법 적용 능력"}, 
    3: {"title": "Part 3. 구문 해석력 (Syntax)", "type": "part3_special", "count": 5, "intent": "단어 힌트가 있어도 구조를 모르면 풀 수 없는 문장을 통해 '감'으로 푸는 습관 적발"}, 
    4: {"title": "Part 4. 문해력 (Literacy)", "type": "part4_special", "count": 5, "intent": "번역된 텍스트의 속뜻을 파악하는 국어적 비문학 소양 및 사고력"}, 
    5: {"title": "Part 5. 문장 연계 (Connectivity)", "type": "part5_special", "count": 5, "intent": "해석을 넘어 문장 간의 논리적 연결 고리(인과, 역접 등) 파악 능력"}, 
    6: {"title": "Part 6. 지문 이해 (Macro-Reading)", "type": "part6_sets", "count": 3, "intent": "지엽적 정보가 아닌 글 전체의 구조(숲)와 필자의 의도를 파악하는 거시적 독해력"},
    7: {"title": "Part 7. 문제 풀이 (Strategy)", "type": "simple_obj", "count": 4, "intent": "순서 배열 및 문장 삽입 등 간접 쓰기 영역에서의 논리적 단서 활용 전략"},
    8: {"title": "Part 8. 서술형 영작 (Writing)", "type": "simple_subj", "count": 5, "intent": "문법적 제약 조건을 완벽히 준수하며 정확한 문장을 구성하는 정밀 영작 능력"}
}

# 파트별 상/중/하 기준 점수 (실질 점수 기준)
# (Mid_Min, High_Min) -> Low: <Mid_Min / Mid: Mid_Min ~ High_Min-1 / High: >= High_Min
PART_THRESHOLDS = {
    1: (50, 75),  # 50미만 하, 50~74 중, 75이상 상
    2: (50, 71),  # 50미만 하, 50~70 중, 71이상 상
    3: (40, 61),  # 40미만 하, 40~60 중, 61이상 상
    4: (50, 71),  # 50미만 하, 50~70 중, 71이상 상
    5: (40, 71),  # 40미만 하, 40~70 중, 71이상 상
    6: (50, 71),  # 50미만 하, 50~70 중, 71이상 상
    7: (40, 71),  # 40미만 하, 40~70 중, 71이상 상
    8: (40, 71)   # 40미만 하, 40~70 중, 71이상 상
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
        
        # '잘 모르겠음' 처리
        if user_ans == "잘 모르겠음":
            results.append({'part': int(part), 'q_id': q_id, 'is_correct': False, 'quadrant': "Deficiency", 'user_ans': user_ans, 'correct_ans': '(미입력)'})
            continue

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
            
        results.append({
            'part': int(part), 
            'q_id': q_id, 
            'is_correct': is_correct, 
            'quadrant': quadrant,
            'user_ans': user_ans,
            'correct_ans': correct_ans
        })
        
    return pd.DataFrame(results)

# ==========================================
# 3. 전문가 분석 텍스트 생성기
# ==========================================

# (1) 예상 등급 분석 (계단식 검증)
def generate_grade_analysis(df_results, student_name):
    part_scores = df_results.groupby('part')['is_correct'].mean() * 100
    all_parts = pd.Series(0, index=range(1, 9))
    part_scores = part_scores.combine_first(all_parts).sort_index()

    avg_basic = int(part_scores[1:4].mean())
    avg_inter = int(part_scores[4:6].mean())
    avg_adv = int(part_scores[6:8].mean())

    predicted_grade = ""
    grade_keyword = ""
    analysis_text = f"{student_name} 학생의 진단 결과를 바탕으로 분석한 예상 등급과 그에 따른 상세 근거입니다. 이번 진단은 기초(Part 1~3), 중위권 소양(Part 4~5), 상위권 관문(Part 6~7) 단계를 순차적으로 통과할 수 있는지를 확인하는 계단식 검증 방식을 따릅니다. "

    if avg_basic < 60:
        predicted_grade = "5등급 이하"
        grade_keyword = "기초 체력 부족 (Foundation Weakness)"
        analysis_text += f"안타깝게도 고등 영어를 소화하기 위한 '기초 체력'이 형성되지 않았습니다. 어휘, 어법, 구문 해석을 포함한 기초 영역(Part 1~3)의 평균 점수가 {avg_basic}점에 머물러 있습니다. 이는 건물을 지을 벽돌과 시멘트가 없는 상태입니다. 지금 당장 고등 진도를 나가는 것은 의미가 없으며, 중등 과정의 핵심 구멍을 메우는 '기초 재건'이 최우선입니다."
    
    elif avg_inter < 60:
        predicted_grade = "4등급"
        grade_keyword = "중위권 소양 부족 (Literacy Gap)"
        analysis_text += f"기초 체력은 어느 정도 갖추었으나, 문장 간의 관계를 파악하고 속뜻을 이해하는 '중위권의 기본 소양'(Part 4~5)에서 병목 현상이 발생했습니다. 단순 해석은 되지만 '무슨 말인지 모르는' 상태입니다. 이 단계에서 막히면 아무리 단어를 많이 외워도 3등급의 벽을 넘기 어렵습니다. 단순 번역을 멈추고 '생각하며 읽는 힘'을 길러야 합니다."
    
    elif avg_adv < 60:
        predicted_grade = "낮은 2등급 ~ 3등급"
        grade_keyword = "상위권 관문 정체 (Strategy Needed)"
        analysis_text += f"기본기와 논리력은 우수하나, 숲을 보고 전략적으로 접근해야 하는 '상위권으로 가는 문'(Part 6~7) 앞에서 멈춰 섰습니다. 글을 너무 정직하게만 읽거나, 유형별 풀이 전략이 부족하여 시간 관리에 실패했을 가능성이 큽니다. 영어 실력이 아니라 '시험 보는 기술(전략)'을 장착해야 안정적인 상위권으로 도약할 수 있습니다."
    
    else:
        total_avg = int(part_scores[1:8].mean())
        if total_avg >= 90:
            predicted_grade = "1등급 ~ 높은 2등급"
            grade_keyword = "완성형 인재 (Masterpiece)"
            analysis_text += f"기초 체력부터 실전 전략까지 흠잡을 데 없는 '완성형 구조'를 갖췄습니다. 상위권으로 가는 문을 활짝 열고 들어간 상태입니다. 이제 남은 과제는 Part 8(서술형)과 같은 킬러 문항에서의 1점 싸움, 그리고 당일 컨디션 관리뿐입니다. 지금의 감각을 유지하며 '만점'을 목표로 달려야 합니다."
        else:
            predicted_grade = "낮은 1등급 ~ 2등급"
            grade_keyword = "안정적 상위권 (Solid Top)"
            analysis_text += f"전 영역에서 고르게 준수한 성적을 거두었습니다. 큰 약점이 없는 육각형 인재에 가깝습니다. 다만 확실한 1등급으로 굳히기 위해서는 '중상위'에 머물러 있는 파트들을 '최상위'로 끌어올리는 정밀 튜닝이 필요합니다."

    return predicted_grade, grade_keyword, analysis_text

# (2) 메타인지 분석 (표에 점수/실질점수 열 추가)
def generate_meta_analysis(df_results, student_name):
    total_cnt = len(df_results)
    if total_cnt == 0: return "데이터 부족", pd.DataFrame()
    
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
    if score_purity < 70: text += "현재 점수에는 상당한 '거품'이 끼어 있습니다. 맞힌 문제라 하더라도 다시 풀면 틀릴 가능성이 높은 '불안한 잠재력' 상태의 문항이 많습니다. "
    else: text += "매우 건강한 수치입니다. 학생이 받은 점수는 요행이 아닌 탄탄한 실력에 기반하고 있어, 어떤 난이도의 시험에서도 쉽게 무너지지 않는 저력을 보여줄 것입니다. "
        
    text += f"\n\n둘째, **오답 고집도(Error Resistance)**는 {int(error_resistance)}%입니다. 이는 틀린 문제 중에서 '몰라서' 틀린 것이 아니라 '맞았다고 착각'한 비율입니다. "
    if error_resistance >= 50: text += "매우 위험한 신호입니다. 학생은 잘못된 개념을 올바른 지식이라고 강하게 믿고 있는 상태입니다. 스스로의 오개념을 깨뜨리는 과정 없이는 성적 향상이 불가능한 '교정 고위험군'입니다. "
    else: text += "양호한 편입니다. 학생은 자신의 부족함을 인정할 줄 아는 열린 태도를 가지고 있어, 올바른 학습법이 제시되면 빠르게 성적을 올릴 수 있는 '학습 스펀지'와 같은 상태입니다. "
        
    text += f"\n\n셋째, **자가 진단 정확도(Calibration Accuracy)**는 {int(calibration_acc)}%입니다. 자신이 아는 것과 모르는 것을 구별하는 능력입니다. 이 능력이 높을수록 아는 것은 건너뛰고 모르는 것에 집중하는 효율적인 학습이 가능합니다.\n\n"
    text += "결론적으로, 점수 뒤에 숨겨진 이 메타인지 패턴을 이해해야 합니다. 모르는 건 죄가 아니지만, '안다고 착각하는 것'은 입시에서 가장 큰 적입니다."

    # 파트별 데이터 계산 (표면점수, 실질점수 추가)
    part_meta_list = []
    for p in range(1, 9):
        p_df = df_results[df_results['part'] == p]
        if p_df.empty: continue
        
        total_p = len(p_df)
        master = len(p_df[p_df['quadrant'] == 'Master'])
        correct = len(p_df[p_df['is_correct'] == True])
        delusion = len(p_df[p_df['quadrant'] == 'Delusion'])
        wrong = total_p - correct
        
        raw_score = int((correct / total_p) * 100)
        real_score = int((master / total_p) * 100)
        
        p_resist = (delusion / wrong * 100) if wrong > 0 else 0
        
        # 자가진단: (Master + Deficiency) / Total
        deficiency = len(p_df[p_df['quadrant'] == 'Deficiency'])
        p_calib = ((master + deficiency) / total_p * 100)
        
        part_meta_list.append({
            "영역": EXAM_STRUCTURE[p]['title'].split('.')[1].strip(),
            "표면 점수": f"{raw_score}점",
            "실질 점수": f"{real_score}점",
            "오답 고집도": f"{int(p_resist)}%",
            "자가 진단 정확도": f"{int(p_calib)}%"
        })
    
    return text, pd.DataFrame(part_meta_list)

# (3) Part 종합 총평 (그룹화 제거, 실질 점수 기반 전체 분석)
def generate_part_overview(df_results, student_name):
    # 파트별 실질 점수 계산
    real_scores = {}
    for p in range(1, 9):
        p_df = df_results[df_results['part'] == p]
        if p_df.empty:
            real_scores[p] = 0
        else:
            master_cnt = len(p_df[p_df['quadrant'] == 'Master'])
            total_cnt = len(p_df)
            real_scores[p] = int((master_cnt / total_cnt) * 100)
            
    # 전체 실질 평균
    avg_real = sum(real_scores.values()) / 8
    
    text = f"단순한 정답률이 아닌, 학생이 '확신을 갖고 정확히 맞힌' **실질 점수(Real Score)**를 기준으로 전체 역량을 분석했습니다. {student_name} 학생의 전체 실질 평균 점수는 **{int(avg_real)}점**입니다.\n\n"
    
    # 최고/최저 영역 분석
    sorted_scores = sorted(real_scores.items(), key=lambda x: x[1], reverse=True)
    best_p, best_s = sorted_scores[0]
    worst_p, worst_s = sorted_scores[-1]
    
    text += f"가장 견고한 실력을 보여준 영역은 **{EXAM_STRUCTURE[best_p]['title'].split('.')[1].strip()} ({best_s}점)**입니다. 이 영역은 운이나 감이 아니라 온전히 본인의 실력으로 점수를 만들어내고 있어, 향후 학습의 든든한 버팀목이 될 것입니다. "
    
    text += f"\n\n반면, 가장 취약한 고리는 **{EXAM_STRUCTURE[worst_p]['title'].split('.')[1].strip()} ({worst_s}점)**입니다. "
    if worst_s < 40:
        text += "현재 실질 점수가 40점 미만으로, 해당 영역에 대한 개념과 기초가 사실상 백지 상태에 가깝습니다. 다른 영역의 학습을 잠시 미루더라도 이 부분에 대한 긴급한 보수 공사가 필요합니다. "
    elif worst_s < 60:
        text += "기본적인 개념은 알고 있으나 확신을 갖고 문제를 해결하지 못하고 있습니다. 헷갈리는 개념을 명확히 정리하지 않으면 전체 성적의 발목을 잡는 병목 구간이 될 것입니다. "
    else:
        text += "전반적으로 우수하나 다른 영역에 비해 상대적으로 자신감이 부족한 상태입니다. 실전 훈련을 통해 확신도를 높이는 전략이 필요합니다. "
        
    # 종합 제언
    gap = best_s - worst_s
    text += "\n\n**[종합 제언]**\n"
    if avg_real >= 80 and gap < 20:
        text += "전 영역에서 실질 점수가 고르게 높습니다. 소위 말하는 '육각형 인재'의 전형입니다. 지금의 학습 밸런스를 유지하면서 킬러 문항 대비에 집중한다면 최상위권 안착이 확실시됩니다."
    elif gap >= 40:
        text += f"영역 간의 편차가 매우 큽니다. 잘하는 것과 못하는 것의 차이가 극명하여, 시험 난이도나 유형에 따라 성적이 널뛸 위험이 있습니다. 강점을 강화하기보다 약점인 **{EXAM_STRUCTURE[worst_p]['title'].split('.')[1].strip()}** 파트를 평균 수준으로 끌어올리는 '밸런스 패치'가 시급합니다."
    else:
        text += "전반적인 학습의 틀은 잡혀있으나, 아직 '확신'의 단계에 이르지 못한 영역들이 존재합니다. 문제를 맞히는 것에 만족하지 말고, '왜 이것이 정답인지'를 설명할 수 있는 메타인지 학습을 통해 실질 점수의 밀도를 높여야 합니다."

    return text

# (4) 파트별 정밀 분석 (실질 점수 기준, 상/중/하 분기, 맞춤형 멘트)
def generate_part_specific_analysis(df_results, student_name):
    part_stats = {}
    for p in range(1, 9):
        p_df = df_results[df_results['part'] == p]
        if p_df.empty:
            part_stats[p] = {'score': 0, 'master': 0, 'lucky': 0, 'delusion': 0}
            continue
        total = len(p_df)
        quads = p_df['quadrant'].value_counts()
        
        # Raw Score & Real Score Calculation
        correct = len(p_df[p_df['is_correct'] == True])
        master = quads.get("Master", 0)
        
        part_stats[p] = {
            'raw_score': int((correct / total) * 100),
            'real_score': int((master / total) * 100), # 실질 점수
            'master_cnt': master,
            'lucky_cnt': quads.get("Lucky", 0),
            'delusion_cnt': quads.get("Delusion", 0)
        }

    detail_analysis_dict = {}
    
    # 멘트 생성 함수 (파트별 로직 분리)
    def get_narrative(part, real_score):
        # 상/중/하 기준 (요청하신 기준 적용)
        thresholds = PART_THRESHOLDS[part] # (Mid_Min, High_Min)
        mid_min, high_min = thresholds
        
        if real_score >= high_min: level = "High"
        elif real_score >= mid_min: level = "Mid"
        else: level = "Low"
        
        # 파트별, 레벨별 멘트 (고정되지 않고 상황에 맞게)
        if part == 1: # 어휘
            if level == "High": return "문맥 속 뉘앙스까지 파악하는 어휘력이 완성 단계입니다. 유의어/반의어 확장 학습으로 빈틈을 메우세요."
            elif level == "Mid": return "기본 단어는 알지만 파생어나 다의어에서 막힙니다. 예문과 함께 단어를 익히는 Context 학습이 필요합니다."
            else: return "어휘량이 절대적으로 부족하여 독해 자체가 불가능한 상태입니다. 매일 꾸준한 단어 암기가 생명줄입니다."
        elif part == 2: # 어법
            if level == "High": return "출제 의도를 간파하는 문법 실력을 갖췄습니다. 서술형 영작으로 연결하는 응용 훈련만 더하면 됩니다."
            elif level == "Mid": return "개념은 들어봤으나 실전 적용에서 헷갈려합니다. 감으로 풀지 말고 근거를 대는 연습이 필요합니다."
            else: return "문법 기초가 무너져 있습니다. 주어와 동사를 찾는 것부터 다시 시작해야 합니다."
        elif part == 3: # 구문
            if level == "High": return "복잡한 문장도 구조적으로 분해하여 정확히 해석합니다. 고난도 장문 독해의 기반이 마련되었습니다."
            elif level == "Mid": return "짧은 문장은 되지만 길어지면 구조를 놓칩니다. 괄호 묶기와 끊어 읽기(Chunking) 훈련이 필수입니다."
            else: return "단어만 연결해서 소설을 쓰고 있습니다. 문장의 뼈대(S+V)를 찾는 훈련이 시급합니다."
        elif part == 4: # 문해력
            if level == "High": return "글의 속뜻과 필자의 의도를 정확히 파악합니다. 국어적 언어 감각이 뛰어납니다."
            elif level == "Mid": return "해석은 했으나 무슨 말인지 모르는 경우가 있습니다. 한 문장 요약 훈련으로 사고력을 키워야 합니다."
            else: return "텍스트 정보를 처리하는 능력이 부족합니다. 쉬운 글부터 정독하며 논지를 파악하는 연습을 하세요."
        elif part == 5: # 연결
            if level == "High": return "문장 간의 논리적 연결 고리를 완벽하게 추적합니다. 순서/삽입 유형의 강자가 될 것입니다."
            elif level == "Mid": return "문장을 따로따로 읽는 경향이 있습니다. 접속사와 지시어를 단서로 앞뒤 관계를 따져야 합니다."
            else: return "글의 흐름을 전혀 타지 못하고 있습니다. '왜 이 문장 다음에 이것이 왔을까?'를 고민해야 합니다."
        elif part == 6: # 지문 이해
            if level == "High": return "나무가 아닌 숲을 보는 거시적 독해력이 탁월합니다. 긴 지문도 두려움 없이 요리할 수 있습니다."
            elif level == "Mid": return "세부 내용에 매몰되어 전체 주제를 놓칩니다. 첫/마지막 문장을 통해 대의를 파악하는 훈련이 필요합니다."
            else: return "긴 글을 읽는 호흡이 너무 짧습니다. 단락별 핵심 내용을 메모하며 읽는 습관을 들이세요."
        elif part == 7: # 전략
            if level == "High": return "출제 의도를 간파하고 효율적으로 점수를 따내는 전략가입니다. 실전 모의고사로 감각을 유지하세요."
            elif level == "Mid": return "유형별 접근법 없이 무작정 읽어서 시간이 부족합니다. 강약 조절과 풀이 스킬을 익혀야 합니다."
            else: return "문제 풀이 경험이 전무합니다. 유형별 풀이 공식부터 차근차근 배워야 합니다."
        elif part == 8: # 영작
            if level == "High": return "문법적 제약을 지키며 정확한 문장을 구사합니다. 감점 없는 만점을 목표로 하세요."
            elif level == "Mid": return "내용은 아는데 사소한 문법 실수로 감점당합니다. 자가 첨삭 훈련으로 디테일을 잡으세요."
            else: return "영작에 대한 두려움이 큽니다. 문장의 뼈대부터 만드는 부분 영작 훈련으로 자신감을 키워야 합니다."
        return ""

    for p in range(1, 9):
        stat = part_stats[p]
        raw = stat['raw_score']
        real = stat['real_score']
        
        # 도입부: 점수 비교 및 거품 진단
        text = f"**{EXAM_STRUCTURE[p]['title']}**\n"
        text += f"이 영역에서 {student_name} 학생이 받은 점수는 **{raw}점**입니다. "
        
        gap = raw - real
        if gap >= 20:
            text += f"그러나 득점 순도(확신도)를 반영한 **실질 점수는 {real}점**으로, 점수 거품이 심각합니다. 운으로 맞힌 문제가 많아 실제 시험에서는 점수가 대폭 하락할 위험이 있습니다. "
        elif gap >= 10:
            text += f"하지만 실질 점수는 **{real}점**으로 다소 차이가 있습니다. 헷갈려서 맞힌 문제들을 내 것으로 만드는 과정이 필요합니다. "
        else:
            text += f"실질 점수 역시 **{real}점**으로, 거품 없이 탄탄한 실력을 갖추고 있습니다. "
            
        # 상세 분석 및 처방 (AI Narrative)
        text += "\n\n" + get_narrative(p, real)
        
        detail_analysis_dict[p] = text

    return detail_analysis_dict

# (5) 종합 평가 및 솔루션 (Part 8 제외 로직 유지)
def generate_total_review(df_results, student_name):
    part_scores = df_results.groupby('part')['is_correct'].mean() * 100
    all_parts = pd.Series(0, index=range(1, 9))
    part_scores = part_scores.combine_first(all_parts).sort_index()
    
    valid_parts = part_scores.drop(8) 
    sorted_parts = valid_parts.sort_values(ascending=True)
    weak_parts_indices = sorted_parts.index[:2].tolist()
    
    weak_titles = [f"**{EXAM_STRUCTURE[p]['title'].split('.')[1].strip()}**" for p in weak_parts_indices]
    avg_weak_score = int(sorted_parts.iloc[:2].mean())

    summary = f"**[진단 요약]**\n"
    summary += f"데이터 분석 결과, {student_name} 학생의 성적 향상을 가로막는 결정적인 병목 구간은 {', '.join(weak_titles)} 영역입니다. "
    summary += f"해당 영역들의 평균 정답률은 약 {avg_weak_score}%로, 전체 학습 균형을 무너뜨리는 주원인이 되고 있습니다. "
    
    delusion_cnt = 0
    for p in weak_parts_indices:
        delusion_cnt += df_results[df_results['part'] == p]['quadrant'].value_counts().get("Delusion", 0)
        
    if delusion_cnt > 0:
        summary += f"특히 해당 파트에서 오답임에도 정답이라고 확신한 문항이 발견되었습니다. 이는 단순 실수가 아니라 개념의 오류가 뿌리 깊게 박혀 있음을 시사합니다. "
    else:
        summary += f"해당 파트에 대한 기초 개념 자체가 정립되지 않아 문제 접근 자체에 어려움을 겪고 있는 상태입니다. "
    summary += "\n\n"

    summary += f"**[우선순위 로드맵]**\n"
    summary += f"성적 상승을 위해 다음 두 가지 학습 목표를 최우선으로 삼아야 합니다. "
    
    roadmap_sentences = []
    for i, p in enumerate(weak_parts_indices):
        title = EXAM_STRUCTURE[p]['title'].split('.')[1].strip()
        order = "첫째" if i == 0 else "둘째"
        
        if p in [1, 2]:
            roadmap_sentences.append(f"{order}, **{title}** 영역의 경우 건물의 기초를 다지듯 중등/고등 필수 개념의 완전 학습을 목표로 해야 합니다. 문제 풀이보다는 개념 암기와 예문 학습 비중을 대폭 늘려야 합니다.")
        elif p in [3, 4]:
            roadmap_sentences.append(f"{order}, **{title}** 영역은 감으로 읽는 습관을 버리고 문장 성분을 쪼개는 구조 독해력을 확보해야 합니다. 정독 훈련을 통해 해석의 정확도를 높여야 합니다.")
        elif p in [5, 6]:
            roadmap_sentences.append(f"{order}, **{title}** 영역은 글의 전개 방식을 파악하여 정답의 논리적 근거를 찾는 연습이 필요합니다. 접속사와 지시어를 단서로 문장 간의 관계를 도식화해야 합니다.")
        else:
            roadmap_sentences.append(f"{order}, **{title}** 영역은 실전 감각 극대화 및 시간 관리 훈련이 필수입니다. 기출 문제를 통해 실전 적응력을 높여야 합니다.")
    
    summary += " ".join(roadmap_sentences) + "\n\n"

    summary += f"**[대세 영어학원의 솔루션]**\n"
    summary += f"저희 학원은 진단된 약점을 보완하기 위해 다음과 같은 이원화된 수업을 진행합니다.\n"
    
    class_action = "우선 **[정규 수업]**에서는 "
    if any(p in [1, 2] for p in weak_parts_indices): class_action += "매 수업 엄격한 어휘/어법 테스트를 통해 개념 숙지 여부를 점검하고, "
    if any(p in [3, 4] for p in weak_parts_indices): class_action += "강사와 함께 문장을 분석하는 '구문 독해 시뮬레이션'을 집중적으로 훈련하며, "
    if any(p in [5, 6] for p in weak_parts_indices): class_action += "지문의 구조를 분석하고 정답의 근거를 찾는 훈련을 실시하며, "
    if any(p in [7] for p in weak_parts_indices): class_action += "실전 모의고사와 킬러 문항 공략을 통해 실전 감각을 극대화합니다. "
    summary += class_action + "\n\n"
    
    summary += "또한, 정규 수업에서 다루기 힘든 개인별 약점은 **[Clinic]** 시간을 통해 해결합니다. "
    clinic_needs = []
    if any(p in [1,2] for p in weak_parts_indices): clinic_needs.append("미통과된 단어/개념 재시험")
    if any(p in [3,4] for p in weak_parts_indices): clinic_needs.append("개별 구문 분석 첨삭")
    if part_scores[8] < 60: clinic_needs.append("1:1 서술형 답안 교정")
    
    if clinic_needs:
        summary += f"특히 학생에게 필요한 **{', '.join(clinic_needs)}**을 1:1로 밀착 지도하여 오개념을 끝까지 추적하고 교정하겠습니다. "
    else:
        summary += "학생이 이해하지 못한 부분을 1:1로 질문받고, 오개념이 교정될 때까지 밀착 지도하겠습니다. "

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
    meta_txt, meta_df = generate_meta_analysis(df_results, student_name)
    part_overview_txt = generate_part_overview(df_results, student_name)
    det_dict = generate_part_specific_analysis(df_results, student_name)
    total_txt = generate_total_review(df_results, student_name)
    
    total_q = len(df_results)
    correct_q = len(df_results[df_results['is_correct'] == True])
    score = int((correct_q / total_q) * 100) if total_q > 0 else 0
    
    c1, c2, c3, c4 = st.columns([2, 2, 3, 2])
    c1.metric("종합 점수", f"{score}점 / 100점")
    c2.metric("맞힌 문제/전체 문제", f"{correct_q}/{total_q}")
    c3.metric("예상 등급", f"{pred_grade} ({grade_kw.split('(')[0]})")
    with c4:
        st.button("🖨️ PDF로 저장", on_click=None, type="primary", key="print_btn")
        if st.session_state.get("print_btn"):
            st.components.v1.html("<script>window.print();</script>", height=0, width=0)
    st.divider()
    
    st.subheader("1. 예상 등급 분석 및 근거")
    st.write(grade_txt)
    st.divider()

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
    
    st.markdown("**[파트별 메타인지 상세 지표]**")
    st.dataframe(meta_df, use_container_width=True, hide_index=True)
    st.divider()

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
    
    st.subheader("4. 파트별 정밀 분석")
    for p in range(1, 9):
        with st.expander(f"{EXAM_STRUCTURE[p]['title']}", expanded=False):
            st.write(det_dict[p])
    st.divider()
    
    st.subheader("5. 종합 평가 및 솔루션")
    st.write(total_txt)

if 'user_email' not in st.session_state: st.session_state['user_email'] = None
if 'user_name' not in st.session_state: st.session_state['user_name'] = None
if 'current_part' not in st.session_state: st.session_state['current_part'] = 1
if 'view_mode' not in st.session_state: st.session_state['view_mode'] = False

if st.session_state['user_email'] is None:
    st.title("🎓 영어 역량 정밀 진단고사")
    st.info("로그인 시 이메일 주소를 사용합니다.")
    tab1, tab2, tab3 = st.tabs(["시험 응시", "분석 리포트", "제출 정답 확인"])
    
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
    with tab3: 
        st.subheader("📋 제출한 답안 상세 보기")
        with st.form("check_details"):
            n_d = st.text_input("이름"); e_d = st.text_input("이메일")
            if st.form_submit_button("답안 조회"):
                if get_student(n_d, e_d):
                    df_detail = calculate_results(e_d)
                    if not df_detail.empty:
                        st.success(f"{n_d}님의 제출 답안입니다.")
                        for p in range(1, 9):
                            st.markdown(f"#### {EXAM_STRUCTURE[p]['title']}")
                            p_data = df_detail[df_detail['part'] == p].copy()
                            if p_data.empty:
                                st.info("제출된 데이터가 없습니다.")
                            else:
                                p_data['결과'] = p_data['is_correct'].apply(lambda x: '🟢 정답' if x else '🔴 오답')
                                display_df = p_data[['q_id', 'user_ans', 'correct_ans', '결과']].rename(columns={
                                    'q_id': '문항 번호', 'user_ans': '제출 답안', 'correct_ans': '실제 정답'
                                })
                                st.dataframe(display_df, use_container_width=True, hide_index=True)
                    else:
                        st.warning("제출된 답안 데이터가 없습니다.")
                else:
                    st.error("학생 정보를 찾을 수 없습니다.")

elif not st.session_state['view_mode'] and st.session_state['current_part'] <= 8:
    part = st.session_state['current_part']
    info = EXAM_STRUCTURE[part]
    st.title(info['title']); st.progress(part/8)
    if part == 8: st.error("⚠️ 서술형 주의: 마침표(.) 필수, 띄어쓰기 주의")
    
    def update_conf(key_ans, key_conf):
        if st.session_state[key_ans] == "잘 모르겠음":
            st.session_state[key_conf] = "모름"

    with st.form(f"exam_{part}"):
        if info['type'] == 'simple_obj':
            for i in range(1, info['count']+1):
                st.markdown(f"**문항 {i}**")
                c1, c2 = st.columns([3,1])
                k_a = f"p{part}_q{i}"; k_c = f"p{part}_c{i}"
                with c1: st.radio(f"Q{i}", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None, label_visibility="collapsed")
                with c2: st.radio("확신도", ["확신","애매","모름"], key=k_c, index=None, label_visibility="collapsed")
                st.markdown("---")
        elif info['type'] == 'part2_special':
            for i in range(1, 10):
                st.markdown(f"**문항 {i}**"); c1, c2 = st.columns([3,1])
                k_a = f"p2_q{i}"; k_c = f"p2_c{i}"
                with c1: st.radio(f"Q{i}", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None, label_visibility="collapsed")
                with c2: st.radio("확신도", ["확신","애매","모름"], key=k_c, index=None)
                st.markdown("---")
            st.markdown("**문항 10**"); c1,c2,c3 = st.columns([2,2,1])
            with c1: st.text_input("틀린단어", key="p2_q10_wrong")
            with c2: st.text_input("고친단어", key="p2_q10_correct")
            with c3: st.radio("확신도", ["확신","애매","모름"], key="p2_c10", index=None)
        elif info['type'] == 'part3_special':
            st.markdown("**문항 1**"); c1,c2=st.columns(2)
            with c1: st.text_input("Main Subject", key="p3_q1_subj")
            with c2: st.text_input("Main Verb", key="p3_q1_verb")
            k_a="p3_q1_obj"; k_c="p3_c1"
            st.radio("정답", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=k_c, index=None); st.markdown("---")
            st.markdown("**문항 2**"); c1,c2=st.columns(2)
            with c1: st.text_input("Main Subject", key="p3_q2_subj")
            with c2: st.text_input("Main Verb", key="p3_q2_verb")
            k_a="p3_q2_obj"; k_c="p3_c2"
            st.radio("정답", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=k_c, index=None); st.markdown("---")
            st.markdown("**문항 3**"); st.text_input("Subject", key="p3_q3_subj")
            k_a="p3_q3_obj"; k_c="p3_c3"
            st.radio("정답", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=k_c, index=None); st.markdown("---")
            st.markdown("**문항 4**"); c1,c2=st.columns(2)
            with c1: st.text_input("Main Subject", key="p3_q4_subj")
            with c2: st.text_input("Main Verb", key="p3_q4_verb")
            k_a="p3_q4_obj"; k_c="p3_c4"
            st.radio("정답", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=k_c, index=None); st.markdown("---")
            st.markdown("**문항 5**"); k_a="p3_q5_obj"; k_c="p3_c5"
            st.radio("정답", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None)
            st.text_input("빈칸", key="p3_q5_text"); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=k_c, index=None); st.markdown("---")
        elif info['type'] == 'part4_special':
            for i in range(1,6):
                st.markdown(f"**문항 {i}**"); k_a=f"p4_q{i}"; k_c=f"p4_c{i}"
                if i in [1,2,5]: st.text_area("답안", key=k_a, height=80)
                else: st.radio("정답", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None)
                st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=k_c, index=None); st.markdown("---")
        elif info['type'] == 'part5_special':
            for i in [1,2]: st.markdown(f"**문항 {i}**"); k_a=f"p5_q{i}_obj"; k_c=f"p5_c{i}"; st.radio("(1)", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None); st.text_input("(2)", key=f"p5_q{i}_text"); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=k_c, index=None); st.markdown("---")
            for i in [3,4]: st.markdown(f"**문항 {i}**"); k_c=f"p5_c{i}"; st.text_input("정답", key=f"p5_q{i}_text"); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=k_c, index=None); st.markdown("---")
            st.markdown("**문항 5**"); k_a="p5_q5_obj"; k_c="p5_c5"; st.radio("(1)", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None); st.text_input("(2)", key=f"p5_q5_text"); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=k_c, index=None); st.markdown("---")
        elif info['type'] == 'part6_sets':
            qg=1
            for s in range(1,4):
                st.markdown(f"### [Set {s}]"); st.text_input(f"Q{qg} Kw", key=f"p6_q{qg}"); k_a1=f"p6_q{qg}_t"; st.radio(f"Q{qg} Tone", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a1, index=None); qg+=1
                k_a2=f"p6_q{qg}_f"; st.radio(f"Q{qg} Flow", ["1","2","3","4","잘 모르겠음"], horizontal=True, key=k_a2, index=None); qg+=1
                st.text_area(f"Q{qg} Sum", key=f"p6_q{qg}"); qg+=1
                st.radio(f"Set {s} 확신도", ["확신","애매","모름"], horizontal=True, key=f"p6_set{s}_conf", index=None); st.markdown("---")
        elif info['type'] == 'simple_subj':
            for i in range(1,6): st.markdown(f"**문항 {i}**"); st.text_area("답안", key=f"p8_q{i}"); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=f"p8_c{i}", index=None); st.markdown("---")

        if st.form_submit_button("제출 및 저장"):
            final_data = []
            is_valid = True
            
            if info['type'] == 'simple_obj':
                for i in range(1, info['count']+1):
                    a = st.session_state.get(f"p{part}_q{i}"); c = st.session_state.get(f"p{part}_c{i}")
                    if a == "잘 모르겠음": c = "모름"
                    if not a: is_valid = False
                    final_data.append({'q_id':str(i), 'ans':a, 'conf':c})
            elif info['type'] == 'part2_special':
                for i in range(1,10):
                    a = st.session_state.get(f"p2_q{i}"); c = st.session_state.get(f"p2_c{i}")
                    if a == "잘 모르겠음": c = "모름"
                    if not a: is_valid = False
                    final_data.append({'q_id':str(i), 'ans':a, 'conf':c})
                w = st.session_state.get("p2_q10_wrong"); o = st.session_state.get("p2_q10_correct"); c = st.session_state.get("p2_c10")
                if not w or not o or not c: is_valid = False
                final_data.append({'q_id':'10_wrong','ans':w,'conf':c}); final_data.append({'q_id':'10_correct','ans':o,'conf':c})
            elif info['type'] == 'part3_special':
                s1=st.session_state.get("p3_q1_subj"); v1=st.session_state.get("p3_q1_verb"); o1=st.session_state.get("p3_q1_obj"); c1=st.session_state.get("p3_c1")
                if o1 == "잘 모르겠음": c1 = "모름"
                if not(s1 and v1 and o1 and c1): is_valid=False
                final_data.extend([{'q_id':'1_subj','ans':s1,'conf':c1},{'q_id':'1_verb','ans':v1,'conf':c1},{'q_id':'1_obj','ans':o1,'conf':c1}])
                s2=st.session_state.get("p3_q2_subj"); v2=st.session_state.get("p3_q2_verb"); o2=st.session_state.get("p3_q2_obj"); c2=st.session_state.get("p3_c2")
                if o2 == "잘 모르겠음": c2 = "모름"
                if not(s2 and v2 and o2 and c2): is_valid=False
                final_data.extend([{'q_id':'2_subj','ans':s2,'conf':c2},{'q_id':'2_verb','ans':v2,'conf':c2},{'q_id':'2_obj','ans':o2,'conf':c2}])
                s3=st.session_state.get("p3_q3_subj"); o3=st.session_state.get("p3_q3_obj"); c3=st.session_state.get("p3_c3")
                if o3 == "잘 모르겠음": c3 = "모름"
                if not(s3 and o3 and c3): is_valid=False
                final_data.extend([{'q_id':'3_subj','ans':s3,'conf':c3},{'q_id':'3_obj','ans':o3,'conf':c3}])
                s4=st.session_state.get("p3_q4_subj"); v4=st.session_state.get("p3_q4_verb"); o4=st.session_state.get("p3_q4_obj"); c4=st.session_state.get("p3_c4")
                if o4 == "잘 모르겠음": c4 = "모름"
                if not(s4 and v4 and o4 and c4): is_valid=False
                final_data.extend([{'q_id':'4_subj','ans':s4,'conf':c4},{'q_id':'4_verb','ans':v4,'conf':c4},{'q_id':'4_obj','ans':o4,'conf':c4}])
                o5=st.session_state.get("p3_q5_obj"); t5=st.session_state.get("p3_q5_text"); c5=st.session_state.get("p3_c5")
                if o5 == "잘 모르겠음": c5 = "모름"
                if not(o5 and t5 and c5): is_valid=False
                final_data.extend([{'q_id':'5_obj','ans':o5,'conf':c5},{'q_id':'5_text','ans':t5,'conf':c5}])
            elif info['type'] == 'part4_special':
                for i in range(1,6):
                    a=st.session_state.get(f"p4_q{i}"); c=st.session_state.get(f"p4_c{i}")
                    if a == "잘 모르겠음": c = "모름"
                    if not a or not c: is_valid=False
                    final_data.append({'q_id':str(i),'ans':a,'conf':c})
            elif info['type'] == 'part5_special':
                for i in [1,2,5]:
                    ao=st.session_state.get(f"p5_q{i if i!=5 else 5}_obj"); at=st.session_state.get(f"p5_q{i if i!=5 else 5}_text"); c=st.session_state.get(f"p5_c{i if i!=5 else 5}")
                    if ao == "잘 모르겠음": c = "모름"
                    if not(ao and at and c): is_valid=False
                    final_data.append({'q_id':f"{i}_obj",'ans':ao,'conf':c}); final_data.append({'q_id':f"{i}_text",'ans':at,'conf':c})
                for i in [3,4]:
                    at=st.session_state.get(f"p5_q{i}_text"); c=st.session_state.get(f"p5_c{i}")
                    if not at or not c: is_valid=False
                    final_data.append({'q_id':f"{i}_text",'ans':at,'conf':c})
            elif info['type'] == 'part6_sets':
                c1=st.session_state.get("p6_set1_conf"); c2=st.session_state.get("p6_set2_conf"); c3=st.session_state.get("p6_set3_conf")
                if not(c1 and c2 and c3): is_valid=False
                qg = 1
                for s in range(1,4):
                    k_kw = f"p6_q{qg}"; a_kw = st.session_state.get(k_kw)
                    if not a_kw: is_valid = False
                    final_data.append({'q_id':str(qg),'ans':a_kw,'conf':eval(f"c{s}")})
                    qg += 1
                    k_t = f"p6_q{qg}_t"; a_t = st.session_state.get(k_t)
                    if not a_t: is_valid = False
                    final_data.append({'q_id':str(qg),'ans':a_t,'conf':eval(f"c{s}")})
                    qg += 1
                    k_f = f"p6_q{qg}_f"; a_f = st.session_state.get(k_f)
                    if not a_f: is_valid = False
                    final_data.append({'q_id':str(qg),'ans':a_f,'conf':eval(f"c{s}")})
                    qg += 1
                    k_s = f"p6_q{qg}"; a_s = st.session_state.get(k_s)
                    if not a_s: is_valid = False
                    final_data.append({'q_id':str(qg),'ans':a_s,'conf':eval(f"c{s}")})
                    qg += 1
            elif info['type'] == 'simple_subj':
                for i in range(1,6):
                    a=st.session_state.get(f"p8_q{i}"); c=st.session_state.get(f"p8_c{i}")
                    if not a or not c: is_valid=False
                    final_data.append({'q_id':str(i),'ans':a,'conf':c})

            if not is_valid:
                st.error("⚠️ 모든 문항의 정답과 확신도를 입력해야 제출할 수 있습니다.")
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
