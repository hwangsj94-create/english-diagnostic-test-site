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
# 3. 전문가 분석 텍스트 생성기 (Narrative Engine)
# ==========================================

# (1) 예상 등급 분석
def generate_grade_analysis(df_results, student_name):
    part_scores = df_results.groupby('part')['is_correct'].mean() * 100
    all_parts = pd.Series(0, index=range(1, 9))
    part_scores = part_scores.combine_first(all_parts).sort_index()

    avg_basic = int(part_scores[1:4].mean()) # P1~3
    avg_inter = int(part_scores[4:6].mean()) # P4~5
    avg_adv = int(part_scores[6:8].mean())   # P6~7

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
    if score_purity < 70: text += "현재 점수에는 상당한 '거품'이 끼어 있습니다. 맞힌 문제라 하더라도 다시 풀면 틀릴 가능성이 높은 '불안한 잠재력' 상태의 문항이 많습니다. "
    else: text += "매우 건강한 수치입니다. 학생이 받은 점수는 요행이 아닌 탄탄한 실력에 기반하고 있어, 어떤 난이도의 시험에서도 쉽게 무너지지 않는 저력을 보여줄 것입니다. "
        
    text += f"\n\n둘째, **오답 고집도(Error Resistance)**는 {int(error_resistance)}%입니다. 이는 틀린 문제 중에서 '몰라서' 틀린 것이 아니라 '맞았다고 착각'한 비율입니다. "
    if error_resistance >= 50: text += "매우 위험한 신호입니다. 학생은 잘못된 개념을 올바른 지식이라고 강하게 믿고 있는 상태입니다. 스스로의 오개념을 깨뜨리는 과정 없이는 성적 향상이 불가능한 '교정 고위험군'입니다. "
    else: text += "양호한 편입니다. 학생은 자신의 부족함을 인정할 줄 아는 열린 태도를 가지고 있어, 올바른 학습법이 제시되면 빠르게 성적을 올릴 수 있는 '학습 스펀지'와 같은 상태입니다. "
        
    text += f"\n\n셋째, **자가 진단 정확도(Calibration Accuracy)**는 {int(calibration_acc)}%입니다. 자신이 아는 것과 모르는 것을 구별하는 능력입니다. 이 능력이 높을수록 아는 것은 건너뛰고 모르는 것에 집중하는 효율적인 학습이 가능합니다. 낮은 경우에는 아는 것을 또 보거나 모르는 것을 안다고 착각하여 시간을 낭비하게 됩니다.\n\n"
    text += "결론적으로, 점수 뒤에 숨겨진 이 메타인지 패턴을 이해해야 합니다. 모르는 건 죄가 아니지만, '안다고 착각하는 것'은 입시에서 가장 큰 적입니다. 이번 진단은 이 '착각'을 수치화하여 보여주었다는 점에서 큰 의미가 있습니다."
    return text

# (3) Part 종합 총평 (전체 AI 내러티브 작성)
def generate_part_overview(df_results, student_name):
    part_scores = df_results.groupby('part')['is_correct'].mean() * 100
    all_parts = pd.Series(0, index=range(1, 9))
    part_scores = part_scores.combine_first(all_parts).sort_index()
    
    # 데이터 집계
    scores = {i: int(part_scores[i]) for i in range(1, 9)}
    max_score = max(scores.values())
    min_score = min(scores.values())
    best_part = max(scores, key=scores.get)
    worst_part = min(scores, key=scores.get)
    avg_total = sum(scores.values()) / 8
    
    text = f"{student_name} 학생의 전체 8개 파트 성취도를 종합적으로 분석한 결과, 전체 평균은 {int(avg_total)}점입니다. "
    
    # 1. 전체적인 형세 판단
    if min_score >= 80:
        text += "전 영역에서 80점 이상의 고득점을 기록하며, 약점을 찾아보기 힘든 '완성형' 구조를 보여주고 있습니다. 기초 체력부터 실전 응용력까지 밸런스가 완벽에 가깝습니다. "
    elif max_score - min_score < 20 and avg_total >= 60:
        text += "전체적으로 큰 기복 없이 고른 실력을 갖추고 있습니다. 특정 영역에서 무너지지 않는다는 점은 긍정적이나, 최상위권 도약을 위해서는 전반적인 실력의 체급을 한 단계 높이는 과정이 필요합니다. "
    elif max_score - min_score >= 40:
        text += f"영역 간의 편차가 매우 큽니다. **{EXAM_STRUCTURE[best_part]['title'].split('.')[1].strip()}** 영역에서는 뛰어난 재능을 보이지만, **{EXAM_STRUCTURE[worst_part]['title'].split('.')[1].strip()}** 영역이 심각하게 발목을 잡고 있습니다. "
    elif avg_total < 50:
        text += "전반적으로 학습 결손이 누적되어 있어 기초 공사가 시급한 상태입니다. 특정 파트의 문제가 아니라 영어 학습 전반에 대한 리빌딩(Rebuilding)이 필요합니다. "

    # 2. 강점과 약점 분석
    best_title = EXAM_STRUCTURE[best_part]['title'].split('.')[1].strip()
    worst_title = EXAM_STRUCTURE[worst_part]['title'].split('.')[1].strip()
    
    text += f"\n\n가장 돋보이는 강점은 **'{best_title}' (Part {best_part})**입니다. 이 영역에서의 성취는 학생의 자신감을 지탱해주는 든든한 버팀목이 될 것입니다. 반면, 가장 시급한 과제는 **'{worst_title}' (Part {worst_part})**의 보완입니다. "
    
    if scores[worst_part] < 50:
        text += f"현재 점수가 {scores[worst_part]}점에 불과하여, 사실상 해당 영역에 대한 기초가 거의 없는 상태입니다. 방치할 경우 전체 등급 하락의 주원인이 될 것입니다. "
    else:
        text += f"점수는 나쁘지 않으나 다른 영역에 비해 상대적으로 경쟁력이 떨어집니다. 이 병목 구간만 뚫어낸다면 전체적인 성적 향상이 기대됩니다. "

    # 3. 마무리 조언
    text += "\n\n종합적으로 볼 때, 학생은 현재의 강점을 유지하되 약점으로 지적된 부분을 집중적으로 공략하는 '선택과 집중' 전략이 필요합니다. 위 그래프에서 움푹 패인 부분이 바로 성적의 물이 새는 구멍임을 인지하고, 이를 메우는 데 학습 에너지를 쏟아야 합니다."

    return text

# (4) 파트별 상세 (완벽하게 분리된 멘트 DB)
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
    
    # 멘트 데이터베이스 (점수대별/파트별 완벽 분리)
    # High: 80~100 / Mid: 50~79 / Low: 0~49
    analysis_db = {
        1: { # 어휘
            "high": "어휘력이 매우 우수합니다. 단순히 단어의 뜻을 아는 것을 넘어 문맥 속에서의 뉘앙스까지 파악하고 있습니다. 지금의 감각을 유지하되, 유의어와 반의어 관계를 정리하며 어휘의 폭을 넓히는 '확장 학습'에 집중한다면 완벽할 것입니다.",
            "mid": "기본적인 어휘는 갖추고 있으나, 다의어나 파생어에서 다소 흔들리는 모습입니다. 아는 단어라고 생각했지만 문맥상 다른 뜻으로 쓰여 해석이 막히는 경우가 있습니다. 단어장을 볼 때 예문을 반드시 함께 읽으며 쓰임새를 익히는 훈련이 필요합니다.",
            "low": "어휘 학습량이 절대적으로 부족합니다. 어휘는 모든 영어 학습의 재료입니다. 재료가 없으니 독해나 문법 공부가 효율이 나지 않는 것입니다. 거창한 계획보다 하루에 30개씩이라도 꾸준히 암기하는 습관을 들이는 것이 가장 시급합니다."
        },
        2: { # 어법
            "high": "문법적 원리를 정확히 꿰뚫고 있습니다. 감으로 푸는 것이 아니라 출제자의 의도를 파악하고 문제에 접근하는 모습이 인상적입니다. 남은 과제는 서술형 영작에서도 이 문법 지식을 오류 없이 활용할 수 있도록 '출력(Output)' 연습을 병행하는 것입니다.",
            "mid": "개념은 어느 정도 알고 있으나 실전 문제에 적용하는 과정에서 실수가 나옵니다. 특히 '감'에 의존하여 답을 고르는 습관이 남아있습니다. 문제를 풀 때 왜 이게 정답인지 문법 용어를 사용하여 설명해보는 '티칭' 훈련을 통해 개념을 단단히 굳혀야 합니다.",
            "low": "문법 용어에 대한 거부감이 있거나, 기초적인 문장 성분(주어, 동사) 구별조차 어려워하는 상태입니다. 무작정 문제만 풀어서는 해결되지 않습니다. 가장 쉬운 입문용 강의를 통해 문법의 뼈대부터 다시 잡아야 합니다."
        },
        3: { # 구문
            "high": "복잡한 문장 구조도 한눈에 파악하는 통찰력을 가졌습니다. 수식어구가 길게 붙어도 주어와 동사를 놓치지 않고 정확하게 해석해냅니다. 이러한 구문 독해력은 고난도 지문을 만났을 때 강력한 무기가 될 것입니다.",
            "mid": "짧은 문장은 잘 해석하지만, 문장이 길어지면 구조를 놓치고 아는 단어만으로 의미를 조합하려는 경향이 있습니다. 문장의 뼈대를 보는 눈을 길러야 합니다. 문장 성분을 괄호로 묶고 끊어 읽는 '청킹(Chunking)' 연습을 추천합니다.",
            "low": "문장을 읽는 것에 대한 두려움이 큽니다. 단어는 드문드문 알아도 이것들이 어떻게 연결되어 무슨 뜻을 만드는지 모르는 상태입니다. 복잡한 문법보다는 '누가(S) / 한다(V) / 무엇을(O)' 순서로 문장을 쪼개 보는 연습부터 시작하세요."
        },
        4: { # 문해력
            "high": "글의 표면적인 정보를 넘어 이면의 함축적 의미까지 파악하는 언어적 센스가 탁월합니다. 필자의 의도를 간파하는 능력은 국어 비문학 학습에도 긍정적인 영향을 줄 것입니다. 다양한 주제의 글을 읽으며 배경지식을 넓혀가세요.",
            "mid": "해석은 했는데 '그래서 무슨 말이지?'라고 되묻는 경우가 있습니다. 글의 정보를 머릿속에서 재구성하는 훈련이 필요합니다. 한 문단을 읽고 나서 보지 않고 핵심 내용을 한 문장으로 요약해보는 연습이 큰 도움이 될 것입니다.",
            "low": "텍스트 자체에 대한 이해도가 낮습니다. 이는 영어 실력의 문제라기보다는 글을 읽고 정보를 처리하는 훈련이 부족한 탓입니다. 긴 글보다는 짧은 글부터 정독하며, 문장과 문장이 어떻게 연결되는지 생각하며 읽는 습관을 길러야 합니다."
        },
        5: { # 문장 연계
            "high": "글의 논리적 흐름을 추적하는 능력이 뛰어납니다. 접속사와 지시어를 단서로 문장 간의 유기적인 관계를 잘 파악하고 있습니다. 순서 배열이나 문장 삽입 같은 고난도 유형에서도 강점을 보일 것으로 예상됩니다.",
            "mid": "문장을 개별적으로는 이해하지만, 앞뒤 문장이 인과인지 역접인지 따지는 데에는 소홀합니다. 접속사나 대명사가 나오면 동그라미를 치고, 앞의 어떤 내용과 연결되는지 화살표로 표시하며 읽는 습관을 들여야 합니다.",
            "low": "글을 읽을 때 흐름이 뚝뚝 끊기는 느낌을 받을 것입니다. 문장 간의 관계를 생각하지 않고 기계적인 번역만 하기 때문입니다. '왜 이 문장 다음에 이 내용이 나왔을까?'를 끊임없이 질문하며 읽어야 논리력이 생깁니다."
        },
        6: { # 지문 이해
            "high": "나무가 아닌 숲을 보는 거시적 독해 능력이 훌륭합니다. 세부 정보에 매몰되지 않고 글 전체의 구조와 주제를 조망할 줄 압니다. 이는 긴 지문을 빠르고 정확하게 읽어내는 효율적인 독해의 핵심입니다.",
            "mid": "열심히 읽었지만 다 읽고 나면 머릿속에 남는 게 별로 없는 타입입니다. 모든 문장을 똑같은 강도로 읽기 때문입니다. 첫 문장과 마지막 문장에 집중하여 글의 전개 방식을 예측하고 확인하는 전략적인 독해가 필요합니다.",
            "low": "긴 지문을 읽는 호흡이 짧습니다. 글을 읽다가 앞부분 내용을 잊어버려 자꾸 되돌아가게 됩니다. 단락별로 핵심 키워드를 메모하며 읽는 습관을 들이면, 긴 글도 놓치지 않고 끝까지 읽어낼 수 있습니다."
        },
        7: { # 문제 풀이
            "high": "출제자의 의도를 간파하고 문제 유형에 맞는 최적의 전략을 구사합니다. 단순히 영어를 잘하는 것을 넘어 '시험을 잘 보는 기술'을 갖추고 있습니다. 실전 모의고사 훈련을 통해 시간 관리 능력만 점검하면 완벽합니다.",
            "mid": "유형별 접근법이 정립되지 않아 비효율적으로 문제를 풀고 있습니다. 모든 지문을 처음부터 끝까지 정직하게 다 읽으려다 시간이 부족해집니다. 유형별로 어디를 먼저 읽고, 어디를 힘빼고 읽어야 하는지 '강약 조절'을 익혀야 합니다.",
            "low": "문제 풀이 경험이 절대적으로 부족합니다. 유형별로 어떻게 접근해야 하는지 몰라 무작정 해석에만 매달리고 있습니다. 각 유형의 특징과 풀이 공식을 익히고, 이를 적용해보는 기본적인 연습부터 시작해야 합니다."
        },
        8: { # 서술형
            "high": "문법적 지식을 바탕으로 정확한 문장을 구성하는 영작 실력이 수준급입니다. 수일치나 시제 같은 디테일한 조건들도 놓치지 않고 꼼꼼하게 챙기는 모습이 인상적입니다. 감점 없는 만점을 목표로 하세요.",
            "mid": "내용은 아는데 영어로 옮길 때 실수가 잦습니다. 어순이 꼬이거나, 관사나 철자 같은 사소한 부분에서 감점을 당합니다. 직접 손으로 써보고, 자신이 쓴 답안을 선생님의 눈으로 꼼꼼하게 자가 첨삭해보는 습관이 필요합니다.",
            "low": "서술형 문제에 대한 막연한 두려움이 있어 손도 대지 못하는 경우가 많습니다. 문장을 통째로 쓰려 하지 말고, 주어와 동사부터 찾는 부분 영작 훈련을 통해 자신감을 키워야 합니다."
        }
    }

    for p in range(1, 9):
        stat = part_stats[p]
        title = EXAM_STRUCTURE[p]['title']
        intent = EXAM_STRUCTURE[p]['intent']
        
        # 점수 구간 결정
        level = "low"
        if stat['score'] >= 80: level = "high"
        elif stat['score'] >= 50: level = "mid"
        
        # 멘트 생성
        text = f"{title} 영역은 {intent}을(를) 진단하는 파트입니다. {student_name} 학생은 이 영역에서 {stat['score']}점을 받았습니다. "
        text += analysis_db[p][level]
        
        # 메타인지 코멘트 (선택적 추가)
        if stat['lucky'] >= 30:
            text += "\n\n추가로, 맞힌 문제 중 상당수가 확신 없이 '감'으로 푼 것으로 나타났습니다. 이는 시험 난이도에 따라 점수가 흔들릴 수 있는 불안 요소이므로, 정답의 근거를 확실히 잡는 훈련이 병행되어야 합니다."
        elif stat['delusion'] >= 30:
            text += "\n\n주의할 점은 틀린 문제를 맞았다고 착각하는 비율이 높다는 것입니다. 이는 잘못된 개념이 자리 잡고 있음을 의미하므로, 반드시 오답 노트를 통해 개념을 바로잡아야 합니다."

        detail_analysis_dict[p] = text

    return detail_analysis_dict

# (5) 종합 평가 및 솔루션 (Part 8 제외 로직)
def generate_total_review(df_results, student_name):
    part_scores = df_results.groupby('part')['is_correct'].mean() * 100
    all_parts = pd.Series(0, index=range(1, 9))
    part_scores = part_scores.combine_first(all_parts).sort_index()
    
    # Part 8 제외하고 하위 2개 파트 선정
    valid_parts = part_scores.drop(8) 
    sorted_parts = valid_parts.sort_values(ascending=True)
    weak_parts_indices = sorted_parts.index[:2].tolist()
    
    weak_titles = [f"**{EXAM_STRUCTURE[p]['title'].split('.')[1].strip()}**" for p in weak_parts_indices]
    avg_weak_score = int(sorted_parts.iloc[:2].mean())

    summary = f"**[진단 요약]**\n"
    summary += f"데이터 분석 결과, {student_name} 학생의 성적 향상을 가로막는 결정적인 병목 구간은 {', '.join(weak_titles)} 영역입니다. "
    summary += f"해당 영역들의 평균 정답률은 약 {avg_weak_score}%로, 전체 학습 균형을 무너뜨리는 주원인이 되고 있습니다. "
    summary += "이러한 불균형을 해소하지 않고 무작정 진도만 나가는 것은 효율이 떨어집니다. 따라서 향후 학습 계획은 이 약점을 최우선으로 보완하는 방향으로 설계되어야 합니다.\n\n"

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
    
    def update_conf(key_ans, key_conf):
        if st.session_state[key_ans] == "잘 모르겠음":
            st.session_state[key_conf] = "모름"

    with st.form(f"exam_{part}"):
        if info['type'] == 'simple_obj':
            for i in range(1, info['count']+1):
                st.markdown(f"**문항 {i}**")
                c1, c2 = st.columns([3,1])
                k_a = f"p{part}_q{i}"; k_c = f"p{part}_c{i}"
                with c1: st.radio(f"Q{i}", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None, label_visibility="collapsed", on_change=update_conf, args=(k_a, k_c))
                with c2: st.radio("확신도", ["확신","애매","모름"], key=k_c, index=None, label_visibility="collapsed")
                st.markdown("---")
        elif info['type'] == 'part2_special':
            for i in range(1, 10):
                st.markdown(f"**문항 {i}**"); c1, c2 = st.columns([3,1])
                k_a = f"p2_q{i}"; k_c = f"p2_c{i}"
                with c1: st.radio(f"Q{i}", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None, label_visibility="collapsed", on_change=update_conf, args=(k_a, k_c))
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
            st.radio("정답", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None, on_change=update_conf, args=(k_a, k_c)); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=k_c, index=None); st.markdown("---")
            st.markdown("**문항 2**"); c1,c2=st.columns(2)
            with c1: st.text_input("Main Subject", key="p3_q2_subj")
            with c2: st.text_input("Main Verb", key="p3_q2_verb")
            k_a="p3_q2_obj"; k_c="p3_c2"
            st.radio("정답", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None, on_change=update_conf, args=(k_a, k_c)); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=k_c, index=None); st.markdown("---")
            st.markdown("**문항 3**"); st.text_input("Subject", key="p3_q3_subj")
            k_a="p3_q3_obj"; k_c="p3_c3"
            st.radio("정답", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None, on_change=update_conf, args=(k_a, k_c)); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=k_c, index=None); st.markdown("---")
            st.markdown("**문항 4**"); c1,c2=st.columns(2)
            with c1: st.text_input("Main Subject", key="p3_q4_subj")
            with c2: st.text_input("Main Verb", key="p3_q4_verb")
            k_a="p3_q4_obj"; k_c="p3_c4"
            st.radio("정답", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None, on_change=update_conf, args=(k_a, k_c)); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=k_c, index=None); st.markdown("---")
            st.markdown("**문항 5**"); k_a="p3_q5_obj"; k_c="p3_c5"
            st.radio("정답", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None, on_change=update_conf, args=(k_a, k_c))
            st.text_input("빈칸", key="p3_q5_text"); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=k_c, index=None); st.markdown("---")
        elif info['type'] == 'part4_special':
            for i in range(1,6):
                st.markdown(f"**문항 {i}**"); k_a=f"p4_q{i}"; k_c=f"p4_c{i}"
                if i in [1,2,5]: st.text_area("답안", key=k_a, height=80)
                else: st.radio("정답", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None, on_change=update_conf, args=(k_a, k_c))
                st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=k_c, index=None); st.markdown("---")
        elif info['type'] == 'part5_special':
            for i in [1,2]: st.markdown(f"**문항 {i}**"); k_a=f"p5_q{i}_obj"; k_c=f"p5_c{i}"; st.radio("(1)", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None, on_change=update_conf, args=(k_a, k_c)); st.text_input("(2)", key=f"p5_q{i}_text"); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=k_c, index=None); st.markdown("---")
            for i in [3,4]: st.markdown(f"**문항 {i}**"); k_c=f"p5_c{i}"; st.text_input("정답", key=f"p5_q{i}_text"); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=k_c, index=None); st.markdown("---")
            st.markdown("**문항 5**"); k_a="p5_q5_obj"; k_c="p5_c5"; st.radio("(1)", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a, index=None, on_change=update_conf, args=(k_a, k_c)); st.text_input("(2)", key=f"p5_q5_text"); st.radio("확신도", ["확신","애매","모름"], horizontal=True, key=k_c, index=None); st.markdown("---")
        elif info['type'] == 'part6_sets':
            qg=1
            for s in range(1,4):
                st.markdown(f"### [Set {s}]"); st.text_input(f"Q{qg} Kw", key=f"p6_q{qg}"); k_a1=f"p6_q{qg}"; st.radio(f"Q{qg} Tone", ["1","2","3","4","5","잘 모르겠음"], horizontal=True, key=k_a1, index=None); qg+=1
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
                    if not a: is_valid = False
                    final_data.append({'q_id':str(i), 'ans':a, 'conf':c})
            elif info['type'] == 'part2_special':
                for i in range(1,10):
                    a = st.session_state.get(f"p2_q{i}"); c = st.session_state.get(f"p2_c{i}")
                    if not a: is_valid = False
                    final_data.append({'q_id':str(i), 'ans':a, 'conf':c})
                w = st.session_state.get("p2_q10_wrong"); o = st.session_state.get("p2_q10_correct"); c = st.session_state.get("p2_c10")
                if not w or not o or not c: is_valid = False
                final_data.append({'q_id':'10_wrong','ans':w,'conf':c}); final_data.append({'q_id':'10_correct','ans':o,'conf':c})
            elif info['type'] == 'part3_special':
                s1=st.session_state.get("p3_q1_subj"); v1=st.session_state.get("p3_q1_verb"); o1=st.session_state.get("p3_q1_obj"); c1=st.session_state.get("p3_c1")
                if not(s1 and v1 and o1 and c1): is_valid=False
                final_data.extend([{'q_id':'1_subj','ans':s1,'conf':c1},{'q_id':'1_verb','ans':v1,'conf':c1},{'q_id':'1_obj','ans':o1,'conf':c1}])
                s2=st.session_state.get("p3_q2_subj"); v2=st.session_state.get("p3_q2_verb"); o2=st.session_state.get("p3_q2_obj"); c2=st.session_state.get("p3_c2")
                if not(s2 and v2 and o2 and c2): is_valid=False
                final_data.extend([{'q_id':'2_subj','ans':s2,'conf':c2},{'q_id':'2_verb','ans':v2,'conf':c2},{'q_id':'2_obj','ans':o2,'conf':c2}])
                s3=st.session_state.get("p3_q3_subj"); o3=st.session_state.get("p3_q3_obj"); c3=st.session_state.get("p3_c3")
                if not(s3 and o3 and c3): is_valid=False
                final_data.extend([{'q_id':'3_subj','ans':s3,'conf':c3},{'q_id':'3_obj','ans':o3,'conf':c3}])
                s4=st.session_state.get("p3_q4_subj"); v4=st.session_state.get("p3_q4_verb"); o4=st.session_state.get("p3_q4_obj"); c4=st.session_state.get("p3_c4")
                if not(s4 and v4 and o4 and c4): is_valid=False
                final_data.extend([{'q_id':'4_subj','ans':s4,'conf':c4},{'q_id':'4_verb','ans':v4,'conf':c4},{'q_id':'4_obj','ans':o4,'conf':c4}])
                o5=st.session_state.get("p3_q5_obj"); t5=st.session_state.get("p3_q5_text"); c5=st.session_state.get("p3_c5")
                if not(o5 and t5 and c5): is_valid=False
                final_data.extend([{'q_id':'5_obj','ans':o5,'conf':c5},{'q_id':'5_text','ans':t5,'conf':c5}])
            elif info['type'] == 'part4_special':
                for i in range(1,6):
                    a=st.session_state.get(f"p4_q{i}"); c=st.session_state.get(f"p4_c{i}")
                    if not a or not c: is_valid=False
                    final_data.append({'q_id':str(i),'ans':a,'conf':c})
            elif info['type'] == 'part5_special':
                for i in [1,2,5]:
                    ao=st.session_state.get(f"p5_q{i if i!=5 else 5}_obj"); at=st.session_state.get(f"p5_q{i if i!=5 else 5}_text"); c=st.session_state.get(f"p5_c{i if i!=5 else 5}")
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
