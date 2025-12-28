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
    1: {"title": "Part 1. 어휘력 (Vocabulary)", "type": "simple_obj", "count": 30, "level": "기초", "intent": "단순 암기가 아닌 문맥 속 의미 파악과 유의어/반의어 활용 능력 점검"},
    2: {"title": "Part 2. 어법 지식 (Grammar)", "type": "part2_special", "count": 10, "level": "기초", "intent": "단순 실수와 개념 부재를 구별하고, 조건에 맞는 문법 적용 능력 확인"}, 
    3: {"title": "Part 3. 구문 해석력 (Syntax)", "type": "part3_special", "count": 5, "level": "중급", "intent": "단어 힌트가 있어도 구조를 모르면 풀 수 없는 문장을 통해 '감'으로 푸는 습관 적발"}, 
    4: {"title": "Part 4. 문해력 (Literacy)", "type": "part4_special", "count": 5, "level": "중급", "intent": "번역된 텍스트의 속뜻을 파악하는 국어적 비문학 소양 및 사고력 측정"}, 
    5: {"title": "Part 5. 문장 연계 (Connectivity)", "type": "part5_special", "count": 5, "level": "상급", "intent": "해석을 넘어 문장 간의 논리적 연결 고리(인과, 역접 등) 파악 능력 진단"}, 
    6: {"title": "Part 6. 지문 이해 (Macro-Reading)", "type": "part6_sets", "count": 3, "level": "상급", "intent": "지엽적 정보가 아닌 글 전체의 구조(숲)와 필자의 의도를 파악하는 거시적 독해력"},
    7: {"title": "Part 7. 문제 풀이 (Strategy)", "type": "simple_obj", "count": 4, "level": "최상급", "intent": "순서 배열 및 문장 삽입 등 간접 쓰기 영역에서의 논리적 단서 활용 전략 점검"},
    8: {"title": "Part 8. 서술형 영작 (Writing)", "type": "simple_subj", "count": 5, "level": "최상급", "intent": "문법적 제약 조건을 완벽히 준수하며 정확한 문장을 구성하는 정밀 영작 능력"}
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
            results.append({'part': int(part), 'q_id': q_id, 'is_correct': False, 'quadrant': "Deficiency"})
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
            
        results.append({'part': int(part), 'q_id': q_id, 'is_correct': is_correct, 'quadrant': quadrant})
        
    return pd.DataFrame(results)

# ==========================================
# 3. 전문가 분석 텍스트 생성기
# ==========================================

# (1) 예상 등급 분석
def generate_grade_analysis(df_results, student_name):
    part_scores = df_results.groupby('part')['is_correct'].mean() * 100
    all_parts = pd.Series(0, index=range(1, 9))
    part_scores = part_scores.combine_first(all_parts).sort_index()

    avg_basic = int(part_scores[1:4].mean())
    avg_inter = int(part_scores[4:6].mean())
    avg_adv = int(part_scores[6:8].mean())

    predicted_grade = ""
    grade_keyword = ""
    analysis_text = f"{student_name} 학생의 진단 결과를 바탕으로 분석한 예상 등급과 그에 따른 상세 근거입니다. 이번 진단은 기초(Part 1~3), 응용(Part 4~5), 심화(Part 6~7) 단계가 순차적으로 완성되어 있는지를 확인하는 계단식 검증 방식을 따릅니다. "

    if avg_basic < 60:
        predicted_grade = "5등급 이하"
        grade_keyword = "기초 재건 필요 (Rebuilding Phase)"
        analysis_text += f"안타깝게도 영어 학습의 뿌리가 되는 기초 체력(어휘, 어법, 구문) 영역의 평균 점수가 {avg_basic}점에 머물러 있습니다. 이 단계가 흔들리면 이후 파트의 점수가 아무리 좋아도 이는 실력이 아닌 '감'에 의존한 일시적인 성과일 뿐입니다. 현재로서는 고등 영어의 진도를 무리하게 나가는 것보다, 중등 과정의 핵심 어휘와 구문부터 다시 점검하여 무너진 기초를 세우는 것이 가장 시급합니다."
    
    elif avg_inter < 60:
        predicted_grade = "4등급"
        grade_keyword = "논리적 도약 필요 (Logical Gap)"
        analysis_text += f"기초 체력(Part 1~3)은 어느 정도 형성되어 있으나, 이를 문장 간의 논리적 연결이나 글의 속뜻 파악으로 확장하는 응용 단계(Part 4~5)에서 병목 현상이 발생했습니다. 해당 구간의 평균 점수는 {avg_inter}점으로, 이는 단순 해석은 가능하지만 '무슨 말인지 모르는' 상태를 의미합니다. 이 단계에서 막히면 3등급의 벽을 넘기 어렵습니다. 4등급 전후로 예측되며, 단순 번역을 넘어선 논리 독해 훈련이 절실합니다."
    
    elif avg_adv < 60:
        predicted_grade = "낮은 2등급 ~ 3등급"
        grade_keyword = "실전 전략 부재 (Strategy Needed)"
        analysis_text += f"기본기와 논리력은 우수하나, 긴 지문을 거시적으로 조망하거나 전략적으로 문제를 해결하는 심화 단계(Part 6~7)에서 평균 {avg_adv}점으로 한계를 보이고 있습니다. 전반적인 영어 실력은 상위권 도약을 목전에 둔 상태이나, 실전 변수를 통제하는 전략이 부족하여 2등급 하위권에서 3등급 사이에 머물 것으로 보입니다."
    
    else:
        total_avg = int(part_scores[1:8].mean())
        if total_avg >= 90:
            predicted_grade = "1등급 ~ 높은 2등급"
            grade_keyword = "완성형 인재 (Masterpiece)"
            analysis_text += f"Part 1부터 7까지 전 영역에서 평균 {total_avg}점이라는 압도적인 성취도를 보이고 있습니다. 어휘, 문법, 논리, 전략 모든 면에서 빈틈이 거의 없는 최상위권 실력입니다. 이제 남은 과제는 Part 8(서술형)과 같은 킬러 문항에서의 디테일한 감점을 막고, 컨디션에 따른 기복을 없애는 것입니다."
        else:
            predicted_grade = "낮은 1등급 ~ 2등급"
            grade_keyword = "안정적 상위권 (Solid Top)"
            analysis_text += f"전 영역 평균 {total_avg}점으로 고르게 준수한 성적을 거두었습니다. 큰 약점이 없는 육각형 인재에 가깝습니다. 다만 확실한 1등급으로 굳히기 위해서는 '중상위'에 머물러 있는 파트들을 '최상위'로 끌어올리는 정밀 튜닝이 필요합니다."

    return predicted_grade, grade_keyword, analysis_text

# (2) 메타인지 분석
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
    if error_resistance >= 50: text += "매우 위험한 신호입니다. 학생은 잘못된 개념을 올바른 지식이라고 강하게 믿고 있는 상태입니다. 스스로의 오개념을 깨뜨리는 과정 없이는 성적 향상이 불가능한 '교정 고위험군'입니다. "
    else: text += "양호한 편입니다. 학생은 자신의 부족함을 인정할 줄 아는 열린 태도를 가지고 있어, 올바른 학습법이 제시되면 빠르게 성적을 올릴 수 있는 '학습 스펀지'와 같은 상태입니다. "
        
    text += f"\n\n셋째, **자가 진단 정확도(Calibration Accuracy)**는 {int(calibration_acc)}%입니다. 자신이 아는 것과 모르는 것을 구별하는 능력입니다. 이 능력이 높을수록 아는 것은 건너뛰고 모르는 것에 집중하는 효율적인 학습이 가능합니다. 낮은 경우에는 아는 것을 또 보거나 모르는 것을 안다고 착각하여 시간을 낭비하게 됩니다.\n\n"
    text += "결론적으로, 점수 뒤에 숨겨진 이 메타인지 패턴을 이해해야 합니다. 모르는 건 죄가 아니지만, '안다고 착각하는 것'은 입시에서 가장 큰 적입니다. 이번 진단은 이 '착각'을 수치화하여 보여주었다는 점에서 큰 의미가 있습니다."
    return text

# (3) Part 종합 총평
def generate_part_overview(df_results, student_name):
    part_scores = df_results.groupby('part')['is_correct'].mean() * 100
    all_parts = pd.Series(0, index=range(1, 9))
    part_scores = part_scores.combine_first(all_parts).sort_index()
    
    groups = {
        "기초 체력 (Part 1)": part_scores[1],
        "문장 구조 분석 (Part 2, 3)": part_scores[2:4].mean(),
        "문해력 (Part 4)": part_scores[4],
        "지문 이해력 (Part 5, 6)": part_scores[5:7].mean(),
        "실전 응용력 (Part 7)": part_scores[7],
        "서술형 영작 (Part 8)": part_scores[8]
    }
    
    text = f"학생의 8개 파트 성취도를 정밀 분석하여 '기초 체력'부터 '서술형 영작'까지 6가지 핵심 역량으로 재구성했습니다. 이는 학생의 학습 상태를 입체적으로 보여주는 지표입니다.\n\n"
    
    group_scores = {}
    for name, score in groups.items():
        score = int(score)
        group_scores[name] = score
        text += f"**• {name}: {score}점** - "
        if score >= 70:
            text += "안정적인 성취도를 보이고 있습니다. 해당 영역의 핵심 개념이 잘 정립되어 있으며, 이를 실전에 적용하는 데 무리가 없습니다. "
        elif score >= 50:
            text += "평균적인 수준이나 다소 기복이 있습니다. 개념은 알고 있으나 응용력이 부족하거나, 특정 유형에서 약점을 보이고 있어 보완이 필요합니다. "
        else:
            text += "학습 결손이 심각한 상태입니다. 해당 영역에 대한 기초 개념이 부재하여 문제 접근 자체가 어렵습니다. 최우선적으로 복구가 필요한 구간입니다. "
        text += "\n"

    max_score = max(group_scores.values())
    min_score = min(group_scores.values())
    best_area = max(group_scores, key=group_scores.get)
    worst_area = min(group_scores, key=group_scores.get)
    gap = max_score - min_score
    
    text += "\n**[종합 분석]**\n"
    if min_score >= 70:
        text += f"전 영역에서 70점 이상의 고른 득점 분포를 보이며, 학습 밸런스가 매우 훌륭합니다. {student_name} 학생은 약점이 없는 '육각형 인재'에 가깝습니다. 지금의 균형을 유지하면서 킬러 문항에 대한 디테일만 다듬는다면 최상위권 안착이 확실시됩니다."
    elif max_score < 50:
        text += "현재 전반적인 영역에서 기초 학습이 시급한 상황입니다. 특정 파트의 문제가 아니라, 영어 학습 전반에 대한 리빌딩(Rebuilding)이 필요합니다. 조급해하지 말고 중등 기초 단어와 구문부터 차근차근 다시 쌓아 올린다면, 오히려 백지 상태에서 더 빠른 성장을 이뤄낼 수 있습니다."
    elif gap >= 40:
        text += f"영역 간 편차가 매우 큽니다. **'{best_area}'**에서는 뛰어난 재능을 보이지만, **'{worst_area}'**가 심각하게 발목을 잡고 있습니다. 잘하는 것에 안주하지 말고, 가장 취약한 '{worst_area}'를 집중적으로 공략하여 무너진 밸런스를 맞추는 것이 급선무입니다."
    else:
        text += f"전반적으로 무난한 성취를 보이고 있으나, **'{worst_area}'** 영역이 다소 아쉽습니다. 다른 영역의 준수한 실력이 점수로 연결되기 위해서는 이 병목 구간을 뚫어야 합니다. 해당 파트만 보완된다면 전체 등급이 한 단계 업그레이드될 것입니다."

    return text

# (4) 파트별 상세
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

    detail_analysis_dict = {}
    
    part_intro = {
        1: "어휘력은 단순 암기가 아니라 문맥 속에서 단어의 의미를 파악하는 능력입니다.",
        2: "어법 지식은 문장을 올바르게 구성하고 해석하는 규칙을 이해하는 것입니다.",
        3: "구문 해석력은 문장의 뼈대(주어/동사)를 찾아 정확한 의미를 도출하는 핵심 역량입니다.",
        4: "문해력은 번역된 문장의 속뜻을 이해하고 요지를 파악하는 비문학적 사고력입니다.",
        5: "문장 연계 능력은 접속사와 지시어를 통해 글의 논리적 흐름을 추적하는 힘입니다.",
        6: "지문 이해 능력은 세부 정보에 매몰되지 않고 글의 전체 구조를 조망하는 능력입니다.",
        7: "문제 풀이 능력은 유형별 특성에 맞춰 효율적으로 정답에 접근하는 전략입니다.",
        8: "서술형 영작은 문법 지식을 바탕으로 조건에 맞는 문장을 완벽하게 구현하는 능력입니다."
    }

    for p in range(1, 9):
        stat = part_stats[p]
        title = EXAM_STRUCTURE[p]['title']
        intent = EXAM_STRUCTURE[p]['intent']
        
        text = f"{title} 영역은 {intent}을(를) 진단하는 파트입니다. {student_name} 학생은 이 영역에서 {stat['score']}점을 받았습니다. {part_intro[p]} "
        
        if stat['score'] >= 80:
            text += "분석 결과, 해당 영역에 대한 이해도가 매우 높습니다. 핵심 개념이 탄탄하게 잡혀있어 실전 문제에서도 흔들림이 없습니다. "
            if stat['lucky'] >= 30:
                text += "다만, 맞힌 문제 중 일부는 '감'으로 해결한 흔적이 보입니다. 이는 컨디션에 따라 점수가 달라질 수 있다는 뜻이므로, 정답의 근거를 명확히 설명하는 훈련을 통해 '운'을 '실력'으로 바꿔야 합니다. "
            elif stat['delusion'] >= 1:
                text += "그러나 소수의 오답 문항에서 '맞았다'고 확신하는 경향이 발견되었습니다. 상위권 싸움에서는 이런 사소한 오개념이 등급을 가릅니다. 틀린 문제는 반드시 오답 노트에 정리하여 개념의 빈틈을 메워야 합니다. "
            else:
                text += "특히 메타인지 상태가 매우 안정적이어서, 학생이 자신의 실력을 정확히 파악하고 있음을 알 수 있습니다. 이 영역은 앞으로도 학생의 든든한 전략 과목이 될 것입니다. "
        
        elif stat['score'] >= 60:
            text += "평균적인 성취도를 보이고 있으나, 상위권 도약을 위해서는 정교함이 더 필요합니다. 기본적인 문제는 해결하지만 응용력이 요구되는 문항에서 다소 고전하고 있습니다. "
            if stat['delusion'] >= 30:
                text += "가장 큰 문제는 틀린 문제를 정답이라고 확신하는 비율이 높다는 것입니다. 이는 잘못된 지식이 머릿속에 굳어져 있음을 의미합니다. 단순 문제 풀이보다는 개념 강의를 다시 수강하거나 교과서를 정독하여 기초를 재정립해야 합니다. "
            else:
                text += "문제 풀이의 정확도가 떨어지고, 정답을 선택할 때 확신을 갖지 못하는 모습입니다. 개념은 알지만 체화되지 않은 상태이므로, 반복적인 실전 훈련을 통해 자신감을 키워야 합니다. "
        
        else:
            text += "기초 학습이 매우 시급한 상태입니다. 해당 영역에 대한 심리적 장벽이 높고, 문제 접근 방식 자체를 찾지 못하고 있습니다. "
            text += "이는 공부량이 부족해서라기보다, 이 단계 이전의 선수 지식이 부족하여 발생한 문제입니다. 지금 무리하게 진도를 나가기보다, 한 단계 아래의 기본서로 돌아가 용어와 원리부터 차근차근 다지는 것이 가장 빠른 길입니다. "

        text += "이러한 현상의 원인을 살펴보면, "
        if p == 1: text += "단어의 표면적인 뜻만 암기하고 문맥 속 뉘앙스를 파악하는 훈련이 부족했기 때문입니다. 예문을 통해 단어의 쓰임새를 익히는 학습이 필요합니다."
        elif p == 2: text += "문법 규칙을 암기만 하고 실제 문장 분석에 적용하는 힘이 약하기 때문입니다. 정답의 근거를 문법 용어로 설명하는 훈련이 필요합니다."
        elif p == 3: text += "문장의 뼈대를 보지 않고 단어만으로 의미를 조합하는 '소설 쓰기식 독해'를 하고 있기 때문입니다. 문장 성분 표시 훈련이 시급합니다."
        elif p == 4: text += "텍스트가 담고 있는 함축적 의미와 논지를 파악하는 '언어적 사고력'이 훈련되지 않았기 때문입니다. 요약 훈련을 병행해야 합니다."
        elif p == 5: text += "문장 간의 연결 고리(접속사, 지시어)를 간과하고 개별 문장 해석에만 집중하기 때문입니다. 흐름을 도식화하는 연습이 필요합니다."
        elif p == 6: text += "세부 정보에 매몰되어 글 전체의 주제를 조망하지 못하기 때문입니다. 첫 문장과 마지막 문장에 집중하여 대의를 파악하는 훈련이 필요합니다."
        elif p == 7: text += "유형별 접근 전략 없이 무작정 읽는 비효율적인 풀이 방식 때문입니다. Scanning과 Skimming 기술을 익혀야 합니다."
        elif p == 8: text += "눈으로 이해하는 것에 익숙해져, 직접 손으로 문장을 구성할 때 챙겨야 할 문법적 디테일을 놓치고 있기 때문입니다. 자가 첨삭 훈련이 필수입니다."

        text += " 따라서 향후 학습은 "
        if p <= 2: text += "무리한 문제 풀이보다는 기본 개념서와 어휘장을 통한 'Input' 학습 비중을 80% 이상으로 늘려야 합니다. 기초가 튼튼하지 않은 상태에서 쌓아 올린 점수는 모래성과 같습니다."
        elif p <= 5: text += "감에 의존한 해석을 멈추고, 문장 성분을 표시하거나 연결 관계를 도식화하는 등 '손을 사용하는 분석 훈련'을 통해 정확성을 높여야 합니다."
        else: text += "단순히 정답을 맞히는 것에 만족하지 말고, '왜 이것이 정답이고 나머지는 오답인지'를 설명할 수 있을 때까지 끈질기게 파고드는 오답 분석 습관을 길러야 합니다."

        detail_analysis_dict[p] = text

    return detail_analysis_dict

# (5) 종합 평가 및 솔루션
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
            roadmap_sentences.append(f"{order}, **{title}** 영역의 경우 건물의 기초를 다지듯 중등/고등 필수 개념의 완전 학습을 목표로 해야 합니다. 문제 풀이보다는 개념 암기와 예문 학습 비중을 대폭 늘려 뿌리부터 튼튼하게 만들어야 합니다.")
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
    meta_txt = generate_meta_analysis(df_results, student_name)
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
                st.markdown(f"### [Set {s}]"); st.text_input(f"Q{qg} Kw", key=f"p6_q{qg}"); qg+=1
                k_a1=f"p6_q{qg}"; st.radio(f"Q{qg} Tone", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a1, index=None); qg+=1
                k_a2=f"p6_q{qg}"; st.radio(f"Q{qg} Flow", ["1","2","3","4","잘 모르겠음"], horizontal=True, key=k_a2, index=None); qg+=1
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
                for i in range(1,5):
                    a=st.session_state.get(f"p6_q{i}")
                    if not a: is_valid=False
                    final_data.append({'q_id':str(i),'ans':a,'conf':c1})
                for i in range(5,9):
                    a=st.session_state.get(f"p6_q{i}")
                    if not a: is_valid=False
                    final_data.append({'q_id':str(i),'ans':a,'conf':c2})
                for i in range(9,13):
                    a=st.session_state.get(f"p6_q{i}")
                    if not a: is_valid=False
                    final_data.append({'q_id':str(i),'ans':a,'conf':c3})
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
