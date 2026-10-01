# -*- coding: utf-8 -*-
"""主体解析：把用户输入识别为 nation / city / school / company，并给出检索清单。"""
from __future__ import annotations

import re

NATION_WORDS = {"", "中国", "全国", "祖国", "中华人民共和国", "china", "cn", "国内"}
SCHOOL_PAT = re.compile(r"(大学|学院|学校|中学|小学|附中|实验(中学|小学)?|幼儿园|职校|技师|中职|高中|初中|院校|书院)")
COMPANY_PAT = re.compile(r"(公司|集团|股份|有限|控股|银行|工厂|实业|科技|研究院|企业|brand|inc|ltd|co\.)")
CITY_PAT = re.compile(r"(市|县|区|省|镇|乡|村|州|盟|旗|地区|新区|开发区|自治州|地区|市辖区)")

# 学校 / 公司 / 城市 各自的 7 大主题（对应 7 天；每天栏目数 = 日期号，共 28 格）
TOPICS = {
    "city": {
        "themes": [
            "城市地标与天际线",
            "重大工程与交通枢纽",
            "产业园区与科技创新",
            "生态水系与公园绿地",
            "历史人文与非遗民俗",
            "民生服务与市井烟火",
            "夜景灯光与未来规划",
        ],
        "notes": [
            "只使用官方发布或主流媒体公开报道的地点与项目，优先选择近三年建成或在建的标志性项目。",
            "名称、地点、建成年代需至少两处独立来源交叉核对；无法核实的条目换成同类备选。",
            "不写“第一”“最强”“必去”等绝对化用语，不输出经纬度。",
        ],
    },
    "school": {
        "themes": [
            "校门与标志性建筑",
            "校园风景与学习空间",
            "课堂与学科特色",
            "实验室与科研平台",
            "体育社团与校园文化",
            "校史沿革与荣誉陈列（不出现人物）",
            "国际交流与未来愿景",
        ],
        "notes": [
            "只使用学校官网、官方公众号、权威媒体报道的公开信息，不得编造排名、人数、升学率、专利号等数据。",
            "不生成可识别的真实人物肖像，不使用校名标准字与校徽的精确复刻，采用抽象化、去标识化处理。",
            "涉及学生图像一律以背影、远景、剪影或空场景代替。",
        ],
    },
    "company": {
        "themes": [
            "品牌理念与总部形象",
            "核心产品与解决方案",
            "智能产线与工厂制造",
            "研发创新与专利墙（抽象化）",
            "团队协作与办公空间",
            "绿色低碳与社会责任",
            "全球化布局与未来愿景",
        ],
        "notes": [
            "只使用企业官网、年报、官方发布与权威媒体报道的公开信息，不得出现未公开数据与客户名称。",
            "不做产品商标与竞品标识的高清复刻，不使用绝对化宣传用语与疗效、收益承诺。",
            "人物以背影、剪影或空场景代替，不出现可识别肖像。",
        ],
    },
}


def _clean(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^(中国|中华人民共和国)\s*(?=[一-龥]{2,}$)", "", t)  # “中国福州” → “福州”
    t = t.replace("的", "").strip(" ，,。.")
    return t


def resolve(text: str) -> dict:
    raw = (text or "").strip()
    name = _clean(raw)
    slug = re.sub(r"[\\/:*?\"<>|\s]+", "-", name).strip("-") or "china"

    if name.lower() in {w.lower() for w in NATION_WORDS}:
        return {
            "type": "nation",
            "subject": "中国",
            "slug": "china",
            "needs_research": False,
            "events_file": "config/events_national.json",
            "topics": [],
            "notes": [],
            "hint": "使用内置国家级素材库，直接生成 7 天海报。",
        }

    if SCHOOL_PAT.search(name):
        kind = "school"
    elif COMPANY_PAT.search(name):
        kind = "company"
    elif CITY_PAT.search(name) or (2 <= len(name) <= 4 and name.isalpha() is False):
        kind = "city"
    else:
        kind = "city"

    info = TOPICS[kind]
    return {
        "type": kind,
        "subject": name,
        "slug": slug,
        "needs_research": True,
        "events_file": f"config/subjects/{slug}.json",
        "topics": info["themes"],
        "notes": info["notes"],
        "hint": (
            f"识别为{kind_map(kind)}：{name}。需要先用联网检索整理 28 个素材条目"
            f"（1+2+…+7），写入 config/subjects/{slug}.json 后再生成海报。"
        ),
    }


def kind_map(kind: str) -> str:
    return {"city": "城市", "school": "学校", "company": "企业", "nation": "全国"}[kind]
