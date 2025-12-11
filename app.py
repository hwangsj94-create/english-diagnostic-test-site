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
# 3. 전문가 분석 텍스트 생성기
# ==========================================

# (1) 예상 등급 분석
def generate_grade_analysis(df_results, student_name):
    part_scores = df_results.groupby('part')['is_correct'].mean() * 100
    all_parts = pd.Series(0, index=range(1, 9))
    part_scores = part_scores.combine_first(all_parts).sort_index()

    score_basic = part_scores[1:3].mean()
    score_syntax = part_scores[3:5].mean()
    score_logic = part_scores[5:7].mean()
    score_killer = part_scores[7:9].mean()

    total_cnt = len(df_results)
    quad_counts = df_results['quadrant'].value_counts()
    delusion_ratio = (quad_counts.get("Delusion", 0) / total_cnt) * 100
    lucky_ratio = (quad_counts.get("Lucky", 0) / total_cnt) * 100

    predicted_grade = ""
    grade_keyword = ""
    analysis_text = f"{student_name} 학생의 진단 결과를 바탕으로 분석한 예상 등급과 그에 따른 상세 근거입니다. 현재의 점수는 단순한 숫자가 아니라, 기초 어휘부터 최상위 킬러 문항까지 이어지는 '학습의 위계'가 얼마나 견고한지를 보여주는 지표입니다. "

    if score_killer >= 85 and delusion_ratio < 10:
        predicted_grade = "1등급"
        grade_keyword = "완성형 인재 (The Perfectionist)"
        analysis_text += "현재 학생은 안정적인 1등급 구간에 위치해 있습니다. 특히 변별력을 가르는 Part 7, 8에서 보여준 성취도는 단순히 영어를 감으로 푸는 것이 아니라 출제자의 의도를 꿰뚫고 있음을 의미합니다. 건전한 메타인지를 유지하고 있어 학습 효율이 극대화된 상태이며, 수능 최저 충족 및 내신 1등급 방어가 충분히 가능합니다."
    elif score_logic >= 80 or score_killer >= 60:
        predicted_grade = "2등급"
        grade_keyword = "불안한 상위권 (The Unstable Top)"
        analysis_text += "우수한 실력을 갖추고 있으나 1등급의 문턱에서 아쉽게 좌절될 수 있는 단계입니다. 구문 해석은 훌륭하지만 논리적 연결성(Part 5, 6)이나 서술형 디테일(Part 8)에서 감점이 발생합니다. 이는 지문의 객관적 단서보다 배경지식이나 감에 의존하는 경향이 있음을 시사합니다."
    elif score_syntax >= 70 or lucky_ratio >= 30:
        predicted_grade = "3등급"
        grade_keyword = "딜레마 구간 (The Keyword Reader)"
        analysis_text += "점수만 보면 중상위권이나, 속을 들여다보면 위태로운 상태입니다. 단어와 문법 지식은 있으나 이를 문장 단위로 엮어내는 '구문 해석력'이 부족하여, 아는 단어로 소설을 쓰는 식의 독해를 하고 있습니다. 특히 확신 없이 맞힌 문제의 비중이 높아 난이도 변화에 취약합니다."
    elif score_basic >= 60:
        predicted_grade = "4등급"
        grade_keyword = "기초 공사 필요 (Structural Failure)"
        analysis_text += "단순히 실력 부족이 아니라 영어를 읽는 것에 대한 심리적 장벽이 존재하는 단계입니다. 어휘 정답률이 낮아 독해 전략이 무의미하며, 문장 구조를 파악하지 못해 해석을 포기하는 경향이 보입니다. 문제 풀이보다는 기초 어휘와 구문 공사에 집중해야 합니다."
    else:
        predicted_grade = "5등급 이하"
        grade_keyword = "잠재적 원석 (The Potential)"
        analysis_text += "아직 고등 영어를 소화할 준비가 되지 않은 상태입니다. 전 영역에 걸쳐 정답률이 낮고 찍기 의존도가 높습니다. 하지만 잘못된 습관이 고착화된 것보다, 백지 상태에서 올바른 방법으로 채워 넣는다면 가장 드라마틱한 성장을 만들 수 있는 기회이기도 합니다."

    return predicted_grade, grade_keyword, analysis_text

# (2) 메타인지 분석 (2번으로 이동됨)
def generate_meta_analysis(df_results, student_name):
    total_cnt = len(df_results)
    if total_cnt == 0: return "데이터 부족"
    
    quad_counts = df_results['quadrant'].value_counts()
    cnt_master = quad_counts.get("Master", 0)
    cnt_lucky = quad_counts.get("Lucky", 0)
    cnt_delusion = quad_counts.get("Delusion", 0)
    cnt_deficiency = quad_counts.get("Deficiency", 0)
    
    correct_total = cnt_master + cnt_lucky
    score_purity = (cnt_master / correct_total * 100) if correct_total > 0 else 0
    wrong_total = cnt_delusion + cnt_deficiency
    error_resistance = (cnt_delusion / wrong_total * 100) if wrong_total > 0 else 0
    calibration_acc = ((cnt_master + cnt_deficiency) / total_cnt) * 100
    
    # [수정] [전문가 분석] 등 제목 제거
    text = f"단순히 몇 개를 틀렸는지보다 중요한 것은, 학생이 자신의 지식 상태를 얼마나 정확하게 인지하고 있느냐입니다. {student_name} 학생의 답안 데이터를 '확신도'와 교차 분석하여 3가지 핵심 지표를 도출했습니다.\n\n"
    text += f"첫째, 학생의 **득점 순도(Score Purity)는 {int(score_purity)}%**입니다. "
    if score_purity < 70: text += "현재 점수에는 상당한 '거품'이 끼어 있습니다. 맞힌 문제라도 다시 풀면 틀릴 가능성이 높은 '불안한 잠재력' 상태의 문항이 많습니다. "
    else: text += "매우 건강한 수치입니다. 학생이 받은 점수는 요행이 아닌 탄탄한 실력에 기반하고 있습니다. "
        
    text += f"\n\n둘째, **오답 고집도(Error Resistance)는 {int(error_resistance)}%**입니다. "
    if error_resistance >= 50: text += "매우 위험한 신호입니다. 틀린 문제의 절반 이상을 '맞았다'고 확신하고 있어, 잘못된 개념이 고착화된 상태입니다. 스스로의 오개념을 깨뜨리는 과정이 필수적입니다. "
    else: text += "양호한 편입니다. 자신의 부족함을 인정할 줄 아는 열린 태도를 가지고 있어, 올바른 학습법이 제시되면 빠르게 성적을 올릴 수 있습니다. "
        
    text += f"\n\n셋째, **자가 진단 정확도(Calibration Accuracy)는 {int(calibration_acc)}%**입니다. 이 능력이 높을수록 아는 것은 건너뛰고 모르는 것에 집중하는 효율적인 학습이 가능합니다.\n\n"
    text += "결론적으로, 점수 뒤에 숨겨진 이 메타인지 패턴을 이해해야 합니다. 모르는 건 죄가 아니지만, '안다고 착각하는 것'은 입시에서 가장 큰 적입니다. 이번 진단은 이 '착각'을 수치화하여 보여주었다는 점에서 큰 의미가 있습니다."
    
    return text

# (3) Part 종합 총평 (3번으로 이동 및 명칭 변경)
def generate_part_overview(df_results, student_name):
    part_scores = df_results.groupby('part')['is_correct'].mean() * 100
    all_parts = pd.Series(0, index=range(1, 9))
    part_scores = part_scores.combine_first(all_parts).sort_index()
    
    # 3대 역량 그룹핑
    score_fund = part_scores[1:3].mean() # 기초
    score_logic = part_scores[3:7].mean() # 논리/독해
    score_killer = part_scores[7:9].mean() # 실전/응용
    
    # [수정] [전문가 분석] 등 제목 제거
    text = f"학생의 8개 파트 성취도를 '기초 체력', '독해 논리력', '실전 응용력'이라는 3대 핵심 역량으로 재구성하여 분석했습니다.\n\n"
    text += f"첫째, 어휘와 어법을 포함한 **'기초 체력' 영역은 {int(score_fund)}점**입니다. "
    if score_fund >= 80: text += "영어를 학습할 수 있는 기본적인 재료가 훌륭하게 갖춰져 있습니다. "
    else: text += "건물을 지을 재료가 부족합니다. 어휘와 문법 기초가 선행되지 않으면 이후 학습은 사상누각이 될 것입니다. "
        
    text += f"\n\n둘째, 문장을 해석하고 글의 맥락을 파악하는 **'독해 논리력' 영역은 {int(score_logic)}점**입니다. "
    if score_logic >= 80: text += "문장 구조를 보는 눈이 정확하고 논리적 사고력이 뛰어납니다. "
    elif score_logic >= 60: text += "해석은 되지만 글 전체를 관통하는 주제를 찾거나 연결 고리를 찾는 데 어려움을 겪고 있습니다. "
    else: text += "문장을 만났을 때 구조적으로 분석하지 못하고 감에 의존한 찍기식 독해를 하고 있습니다. "
        
    text += f"\n\n셋째, 고난도 문제 해결과 영작을 포함한 **'실전 응용력' 영역은 {int(score_killer)}점**입니다. "
    if score_killer >= 80: text += "1등급을 결정짓는 킬러 문항에 대한 방어력이 상당합니다. "
    else: text += "결국 점수를 깎아먹는 것은 이 구간입니다. 서술형에서의 사소한 실수들이 등급 하락의 주원인이 되고 있습니다."
        
    text += "\n\n종합적으로 볼 때, 학생은 특정 영역의 강점을 살리기보다 무너진 균형을 맞추는 것이 급선무입니다. 가장 낮게 나타난 영역이 바로 학생의 '성적 발목'을 잡고 있는 구간임을 인지해야 합니다."
    return text

# (4) 파트별 상세 (처방 명칭 변경)
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

    expert_db = {
        1: {'cause': "단어의 표면적 뜻만 암기하고 문맥 속 활용 능력이 부족합니다.", 'risk': "해석이 매끄럽게 안 되는 현상이 발생합니다.", 'solution': "예문을 통한 'Context 학습'이 필요합니다."},
        2: {'cause': "문법 원리를 파악하지 못하고 '감'에 의존하고 있습니다.", 'risk': "내신 서술형 감점 및 수능 어법 확신 부족으로 이어집니다.", 'solution': "정답 근거를 설명하는 '티칭' 훈련이 필요합니다."},
        3: {'cause': "문장 뼈대를 못 찾고 단어를 조합해 소설을 쓰고 있습니다.", 'risk': "고난도 긴 문장에서 오독할 확률이 높습니다.", 'solution': "**'청킹(Chunking)'** 훈련과 직독직해 연습이 시급합니다."},
        4: {'cause': "한글 해석을 봐도 무슨 말인지 모르는 '비문학적 소양' 부족입니다.", 'risk': "빈칸 추론 등 고난도 유형에서 무너집니다.", 'solution': "한 문장 요약 훈련과 사고 구체화 훈련이 필요합니다."},
        5: {'cause': "접속사, 지시어 등 논리 연결 고리를 간과하고 있습니다.", 'risk': "순서 배열 유형에서 시간을 허비하게 됩니다.", 'solution': "앞뒤 문장의 논리적 관계(순접/역접)를 따지는 습관을 길러야 합니다."},
        6: {'cause': "세부 해석에 매몰되어 글 전체의 '주제'를 놓치고 있습니다.", 'risk': "지문을 다 읽고도 내용을 모르는 상황이 반복됩니다.", 'solution': "첫/마지막 문장으로 결론을 예측하는 '거시적 독해'가 필요합니다."},
        7: {'cause': "유형별 전략 없이 무작정 읽는 비효율적 방식을 고수합니다.", 'risk': "시간 부족으로 쉬운 문제도 놓치게 됩니다.", 'solution': "Scanning/Skimming 전략을 체화해야 합니다."},
        8: {'cause': "문법 지식을 Output으로 전환하는 훈련이 부족합니다.", 'risk': "내신 1등급을 놓치는 결정적 원인이 됩니다.", 'solution': "손으로 쓰는 영작 훈련과 자가 첨삭 습관이 필요합니다."}
    }

    detail_analysis_dict = {}
    for p in range(1, 9):
        stat = part_stats[p]
        info = expert_db[p]
        text = f"**[진단]** 점수 {stat['score']}점. "
        if stat['score'] >= 80: text += "우수하나 " + ("운이 작용했습니다." if stat['lucky']>=30 else "안정적입니다.")
        elif stat['score'] >= 60: text += "중위권이며 " + ("개념 정립이 필요합니다." if stat['lucky']<30 else "찍은 문제가 많습니다.")
        else: text += "기초 학습이 시급합니다."
        text += f"\n**[원인]** {info['cause']}\n**[위험]** {info['risk']}\n**[처방]** {info['solution']}"
        detail_analysis_dict[p] = text

    return detail_analysis_dict

# (5) 종합 평가 및 솔루션 (다수 취약점 선정 + 서술형 로직 + 정규/클리닉 분리)
def generate_total_review(df_results, student_name):
    part_scores = df_results.groupby('part')['is_correct'].mean() * 100
    all_parts = pd.Series(0, index=range(1, 9))
    part_scores = part_scores.combine_first(all_parts).sort_index()
    
    # [수정] 점수 낮은 순으로 정렬하여 하위 2개 이상 선택
    sorted_parts = part_scores.sort_values(ascending=True) # 오름차순
    # 상위 2개 추출 (점수가 동일하면 인덱스(파트번호) 순)
    weak_parts_indices = sorted_parts.index[:2].tolist()
    
    # 1. 진단 요약
    summary = f"**[진단 요약]**\n"
    summary += f"데이터 분석 결과, {student_name} 학생의 성적 향상을 위해 가장 시급하게 보완해야 할 영역은 "
    
    weak_titles = [f"**{EXAM_STRUCTURE[p]['title'].split('.')[1].strip()} (Part {p})**" for p in weak_parts_indices]
    summary += f"{', '.join(weak_titles)}입니다. "
    
    avg_weak_score = int(sorted_parts.iloc[:2].mean())
    summary += f"해당 영역들의 평균 정답률은 약 {avg_weak_score}%로, 전체 학습 균형을 무너뜨리는 주원인이 되고 있습니다. "
    summary += "단순히 열심히 하는 것으로는 부족하며, 해당 취약점들을 핀셋처럼 집어내는 전략적 학습이 필요합니다.\n\n"

    # 2. 우선순위 로드맵 (텍스트 서술형, 2개 파트 이상)
    summary += f"**[우선순위 로드맵]**\n"
    summary += f"성적 상승을 위해 다음 두 가지 학습 목표를 최우선으로 삼아야 합니다. "
    
    roadmap_sentences = []
    for p in weak_parts_indices:
        title = EXAM_STRUCTURE[p]['title'].split('.')[1].strip()
        if p in [1, 2]:
            roadmap_sentences.append(f"첫째, **Part {p}({title})**의 경우 건물의 기초를 다지듯 중등/고등 필수 개념의 완전 학습을 목표로 해야 합니다. 문제 풀이보다는 개념 암기와 예문 학습 비중을 대폭 늘리는 것이 중요합니다.")
        elif p in [3, 4]:
            roadmap_sentences.append(f"둘째, **Part {p}({title})**는 감으로 읽는 습관을 버리고 문장 성분을 쪼개는 구조 독해력을 확보해야 합니다. 모든 문장의 주어와 동사를 표시하고 끊어 읽는 정독 훈련을 수행해야 합니다.")
        elif p in [5, 6]:
            roadmap_sentences.append(f"셋째, **Part {p}({title})**는 글의 전개 방식을 파악하여 정답의 논리적 근거를 찾는 연습이 필요합니다. 접속사와 지시어를 단서로 문장 간의 관계를 도식화하며 읽어야 합니다.")
        else:
            roadmap_sentences.append(f"넷째, **Part {p}({title})**는 실전 감각 극대화 및 서술형 감점 요인을 제거하는 디테일 훈련이 필수입니다. 시간 제한을 둔 풀이와 영작 후 자가 첨삭 훈련을 반복해야 합니다.")
    
    summary += " ".join(roadmap_sentences) + "\n\n"

    # 3. 학원의 솔루션 (정규/클리닉 분리)
    summary += f"**[대세 영어학원의 솔루션]**\n"
    summary += f"저희 학원은 진단된 약점을 보완하기 위해 다음과 같은 이원화된 수업을 진행합니다.\n"
    
    # 정규 수업 (Group Activity Only)
    class_action = ""
    for p in weak_parts_indices:
        if p in [1, 2]: class_action += "매 수업 엄격한 어휘/어법 테스트와 구두 테스트를 통해 개념을 완벽히 숙지시킵니다. "
        elif p in [3, 4]: class_action += "수업 시간에 강사와 함께 문장을 분석하는 '구문 독해 시뮬레이션'을 집중적으로 훈련합니다. "
        elif p in [5, 6]: class_action += "지문의 구조를 분석하고 정답의 근거를 형광펜으로 표시하게 하는 '근거 찾기 훈련'을 실시합니다. "
        else: class_action += "실전 모의고사 풀이와 킬러 문항 집중 공략을 통해 실전 감각을 극대화합니다. "
    
    summary += f"- **정규 수업:** {class_action}\n"
    
    # 클리닉 (1:1 Care)
    clinic_action = "정규 수업에서 다루기 힘든 개인별 약점은 **'Clinic'** 시간에 해결합니다. "
    clinic_needs = []
    if any(p in [1,2] for p in weak_parts_indices): clinic_needs.append("미통과된 단어/개념 재시험")
    if any(p in [3,4] for p in weak_parts_indices): clinic_needs.append("개별 구문 분석 첨삭")
    if any(p in [7,8] for p in weak_parts_indices): clinic_needs.append("1:1 서술형 답안 교정")
    
    if clinic_needs:
        clinic_action += f"특히 {student_name} 학생에게 필요한 **{', '.join(clinic_needs)}**을 1:1로 밀착 지도하여 오개념을 끝까지 추적하고 교정하겠습니다."
    else:
        clinic_action += "학생이 이해하지 못한 부분을 1:1로 질문받고, 오개념이 교정될 때까지 끝까지 확인하겠습니다."

    summary += f"- **Clinic (1:1 케어):** {clinic_action}\n\n"

    # 4. 필수 결론 멘트
    summary += "정밀한 진단은 모두 끝났습니다. 이제 남은 것은 처방전입니다. 대세 영어학원 지축 캠퍼스에서 황성진, 김찬종 두 명의 원장이 직접 책임지겠습니다. 다시 돌아오지 않는 이 시간, 우리 아이에게 가장 필요한 학습으로 지도할 것을 약속 드립니다."

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

    # 2. 메타인지 분석 (순서 변경됨)
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
        # [전문가 분석] 텍스트 제거
        st.write("\n") 
        st.write(meta_txt)
    st.divider()

    # 3. Part 종합 총평 (순서 변경 및 명칭 변경)
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
        # [전문가 총평] 텍스트 제거
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
    st.success(total_txt)

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
