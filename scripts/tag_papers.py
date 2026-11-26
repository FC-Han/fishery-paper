#!/usr/bin/env python3
"""
论文标签引擎
为每篇论文打上四维标签：研究主题 / 研究鱼种 / 海域区域 / 方法手段

设计：
- 纯规则 + 词典，零成本、可解释、结果稳定，无需 API Key
- 标题命中权重 x3，摘要命中权重 x1（同一关键词摘要内最多累计 3 次）
- 每个维度按得分排序取 TopN，得分低于阈值丢弃

用法：
  python tag_papers.py            # 给缺标签的论文打标
  python tag_papers.py --force    # 全部重新打标（改了词库后用）
"""

import html as htmllib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "papers.json"

TITLE_WEIGHT = 3
ABS_WEIGHT = 1
ABS_MAX_HITS = 3

# 各维度命中阈值（主题需更强证据，方法与地域单次摘要命中即可）
MIN_SCORE = {"theme": 3, "species": 3, "region": 2, "method": 2}

# 每个维度最多保留几个标签
CAP = {"theme": 3, "species": 4, "region": 2, "method": 3}

# 明确不属于渔业科学的领域，命中即判无关
# STRICT：领域标志词，在渔业论文里基本不会出现（工程、航运、管理、昆虫）
OFF_TOPIC_STRICT = [
    # 勘误 / 撤稿通知，不是研究论文
    "correction:", "erratum", "retraction note", "expression of concern",
    # 船舶 / 航运 / 港口 / 海事管理
    "shipping emission", "port state measure", "deck cadet", "container shipping",
    "port importance", "seafarer", "ship crew", "maritime education",
    # 海岸与海洋工程
    "sea dike", "revetment", "wave overtopping", "monopile",
    "oscillating hydrofoil", "fowler flap", "tidal energy converter",
    "calcareous sand", "permeability prediction",
    # 化工 / 能源调度
    "chemical energy dispatch", "energy scheduling", "beetle antennae",
    # 管理 / 人类行为
    "green hrm", "human resource management", "fuzzy ahp", "candidate selection",
    # 昆虫 / 陆生植物
    "heteroptera", "rose plantation", "sticky trap", "agrilus",
]

# SOFT：渔业论文里也可能出现的词（鱼类外科手术、肿瘤研究、混凝土池、包装、明胶等），
#       只有在鱼种/渔业主题等正向证据之后仍无支撑，才判为无关
OFF_TOPIC_SOFT = [
    # 临床医学
    "case report", "a case of", "perforation", "abscess", "peritonitis",
    "duodenal", "intrahepatic", "esophagus", "oesophagus", "patient",
    "surgical", "carcinoma", "tumor", "lipoma", "sarcoma",
    "in situ hybridization", "retrospective study", "wound healing", "drug delivery",
    # 材料 / 食品工程
    "hydrogel", "adsorption", "photocatal", "edible film", "packaging",
    "nanoparticle synthesis", "antimicrobial peptide film", "concrete",
    # 法律 / 人文 / 社科（渔业法、渔业史一类对科研读者价值低）
    "gambling", "mosaic", "preaching", "litigation", "criminal liability",
    "taxation", "jurisprudence",
]

# 仿生机器人：研究对象是机器不是鱼，但只在标题上判——
# 真正的鱼类论文（如飞鱼滑翔）也会在摘要里提 "biomimetic robots"
ROBOTIC = ["robotic fish", "bionic fish", "robot fish", "biomimetic robot",
           "underactuated", "trajectory tracking"]

# 医学/临床类期刊：即使正文提到 fish 也不是渔业研究
MEDICAL_JOURNAL_PATS = [
    "cureus", "clinical case", "surgical patholog", "diagnostic",
    "health scien", "medical journal", "medical case", "case reports",
    "oncology", "radiology", "nursing", "allergolog", "pharmacolog",
    "clinical immunolog",
]

OFF_TOPIC = OFF_TOPIC_STRICT + OFF_TOPIC_SOFT

# 渔业 / 水产 / 水生生物学专业期刊：主题天然契合，不做相关性审查
TRUSTED_JOURNAL_PATS = [
    "fish biology", "fish and fisheries", "fisheries science", "fisheries research",
    "fisheries management", "fisheries oceanography", "reviews in fish",
    "reviews in aquaculture", "reviews in fisheries",
    "canadian j. fisheries", "canadian journal of fisheries",
    "north american journal of fisheries", " american fisheries society",
    "ices journal of marine science", "aquaculture", "fishes", "fisheries",
    "fish diseases", "fish & shellfish", "ecology of freshwater fish",
    "ichthyolog", "journal of shellfish research", "marine and coastal fisheries",
    "aquatic living resources", "latin american journal of aquatic research",
    "aquatic conservation", "aquatic toxicology", "aquaculture environment",
]

# 渔业核心主题：命中即认定与渔业相关（区别于 misc 兜底）
CORE_THEMES = {"aqua", "stock"}

# 强渔业信号词：综合刊 / 海洋工程刊里的论文靠正文自证
STRONG_FISH = re.compile(
    r"\b(fish(?:es|ery|eries|ing)?|"
    r"aquacultur\w*|mariculture|shellfish|seafood|bivalve\w*|mollusc\w*|"
    r"broodstock|hatchery|fingerling|aquafeed|juvenile fish|"
    r"overfish\w*|stock assessment|bycatch|trawl\w*|gillnet|longline|"
    r"shrimp|prawn|crayfish|crab|lobster|oyster|mussel|scallop|clam|abalone|sea ?urchin|"
    r"salmon|trout|tilapia|carp|catfish|tuna|cod|haddock|halibut|"
    r"sea ?bream|seabream|seabass|flounder|grouper|snapper|mullet|eel|"
    r"shark|roughshark|stingray|skate|"
    r"kelp|seaweed|macroalg\w*|diatom|plankton|zooplankton|phytoplankton|"
    r"benthos|macrobenthos|benthic invertebrate|"
    r"seagrass|mangrove|coral reef|fish assemblage|fishery|"
    r"marine ranching|sea ranch)\b",
    re.IGNORECASE,
)

DIMENSIONS = {
    "theme": {"label": "研究主题", "color": "teal"},
    "species": {"label": "研究鱼种", "color": "coral"},
    "region": {"label": "海域区域", "color": "indigo"},
    "method": {"label": "方法手段", "color": "amber"},
}


def T(tid, zh, en, pats):
    return {"dim": "theme", "id": tid, "zh": zh, "en": en, "pats": pats}


def S(tid, zh, en, pats):
    return {"dim": "species", "id": tid, "zh": zh, "en": en, "pats": pats}


def G(tid, zh, en, pats):
    return {"dim": "region", "id": tid, "zh": zh, "en": en, "pats": pats}


def M(tid, zh, en, pats):
    return {"dim": "method", "id": tid, "zh": zh, "en": en, "pats": pats}


RULES = [
    # ==================== 研究主题 ====================
    T("stock", "种群评估与管理", "Stock assessment & management", [
        "stock assessment", "population dynamic", "population model", "population viability",
        "maximum sustainable yield", "!msy!", "fishing mortality", "exploitation rate",
        "reference point", "harvest control", "harvest strategy", "catch limit", "quota",
        "age-structured", "catch-at-age", "surplus production", "recruitment variability",
        "fisheries management", "fishery management", "management strateg", "allowable catch",
        "rebuilding plan", "overfish", "overexploit", "depleted stock", "stock status",
        "cpue standard", "stock structure", "fishery-independent", "assessment model",
        "total allowable catch", "fishing pressure", "biomass", "recruitment",
        "stock dynamics", "!stock!", "population synchrony", "synchrony",
        "depensation", "density dependence", "mortality estimate", "cohort",
    ]),
    T("aqua", "水产养殖", "Aquaculture", [
        "aquaculture", "mariculture", "fish farm", "cage cultur", "pond cultur",
        "recirculating aquaculture", "!ras!", "hatchery", "broodstock", "stocking density",
        "polyculture", "integrated multi-trophic", "!imta!", "aquafeed", "formulated diet",
        "feed conversion", "growth performance", "survival rate", "fingerling",
        "juvenile rearing", "nursery production", "breeding program", "selective breeding",
        "aquaponic", "extensive pond", "intensive cultur", "seed production", "restocking",
        "sea ranch", "culture system", "farming practice", "grow-out",
    ]),
    T("bio", "生物学与生理", "Biology & physiology", [
        "physiolog", "osmoregulation", "metabolic rate", "metabolism", "thermal tolerance",
        "swimming performance", "critical swimming", "age and growth", "maturity",
        "gonadosomatic", "gonad development", "fecundity", "spawning", "sex differentiation",
        "sex reversal", "endocrine", "hormone", "cortisol", "stress response",
        "hematolog", "histolog", "larval development", "ontogeny", "morphometric",
        "feeding behavior", "digestive enzyme", "condition factor", "length-weight",
        "growth model", "somatic growth", "reproductive strateg", "puberty", "vitellogenin",
        "early life history", "embryonic development", "oxygen consumption",
        "dispersal", "swim speed", "swimming", "locomot", "growth variation",
        "young-of-year", "!ontogenetic", "body size", "allometr", " !vision",
    ]),
    T("eco", "生态与栖息地", "Ecology & habitat", [
        "habitat", "food web", "trophic", "diet composition", "stomach content", "niche",
        "community structure", "assemblage", "species richness", "biodiversity",
        "nursery ground", "seagrass", "mangrove", "salt marsh", "coral reef", "estuar",
        "riverine", "riparian", "migration", "spawning ground", "connectivity",
        "ecosystem function", "predator-prey", "zooplankton", "phytoplankton", "benthic",
        "macrobenthos", "primary production", "eutrophication", "regime shift",
        "ecological role", "depth distribution", "habitat suitability", "occupancy",
        "species co-occurrence", "stream flow", "hydrolog", "wetland", "lagoon", "reef fish",
        "trophic level", "ecological network", "food chain", "benthic community",
        "fish assemblage", "community composition", "!spatial distribution",
    ]),
    T("climate", "气候变化与环境", "Climate change & environment", [
        "climate change", "warming", "ocean acidif", "acidification", "deoxygenation",
        "hypoxia", "hypoxic", "marine heatwave", "heat wave", "sea surface temperature",
        "!sst!", "climate projection", "future scenario", "!ssp!", "!rcp!", "el niño",
        "!enso!", "upwelling", "extreme event", "drought", "flood", "hydrologic extreme",
        "carbonate chemistry", "dissolved oxygen", "thermal stress", "range shift",
        "poleward", "global warming", "emission scenario", "climate model",
        "oceanograph", "physical driver", "environmental driver", "climatic",
        "resilience", "environmental variability", "seasonal variability",
    ]),
    T("gene", "遗传与基因组", "Genetics & genomics", [
        "genetic", "genomic", "transcriptom", "proteom", "metabolom", "!snp!",
        "!gwas!", "population structure", "phylogeograph", "phylogen", "haplotype",
        "mitogenom", "genome assembly", "epigenetic", "methylation", "hybridization",
        "introgression", "inbreeding", "effective population size", "microsatellite",
        "parentage", "marker-assisted", "gene expression", "differentially expressed",
        "!dna!", "rna-seq", "whole-genome", "genetic diversity", "local adaptation",
    ]),
    T("disease", "疾病与免疫", "Disease & immunity", [
        "disease", "pathogen", "virulence", "infection", "immune", "immun", "vaccin",
        "antibody", "virus", "viral", "bacterial", "bacteri", "parasite", "parasit",
        "!aeromonas!", "!vibrio!", "streptococcus", "edwardsiella", "!wssv!", "!ahpnd!",
        "!isavirus!", "sea lice", "lepeophtheirus", "mass mortality", "mortality event",
        "antimicrobial", "antibiotic", "microbiota", "microbiome", "gill disease",
        "saprolegnia", "co-infection", "outbreak", "susceptibility", "resistance gene",
        "!lesion", "!ulcer", "!necro", "hemocyte", "lysozyme", "inflammatory",
    ]),
    T("nutri", "营养与饲料", "Nutrition & feed", [
        "nutrition", "nutritional", "dietary", "protein level", "lipid level",
        "fatty acid", "amino acid", "fishmeal", "fish meal", "fish oil", "soybean meal",
        "feed additive", "supplementation", "!vitamin!", "!mineral!", "taurine",
        "phospholipid", "feed efficiency", "feeding rate", "attractant", "palatability",
        "diet formulation", "feed ingredient", "plant protein", "insect meal",
        "alternative protein", "nutrient requirement", "feed intake", "apparent digestibility",
    ]),
    T("pollution", "污染与毒理", "Pollution & toxicology", [
        "pollution", "pollutant", "contaminant", "heavy metal", "!mercury!", "!cadmium!",
        "!arsenic!", "microplastic", "nanoplastic", "!pfas!", "!pcb!", "!dioxin!",
        "pesticide", "herbicide", "insecticide", "toxicity", "toxic", "bioaccumulat",
        "biomagnif", "oil spill", "hydrocarbon", "pharmaceutical", "drug residue",
        "effluent", "wastewater", "sewage", "ecotoxicolog", "endocrine disrupt",
        "plastic debris", "marine debris", "antifouling", "aquaculture effluent",
    ]),
    T("conserv", "保护与恢复", "Conservation & restoration", [
        "conservation", "endangered", "threatened", "!iucn!", "red list", "protected area",
        "marine protected area", "!mpa!", "marine reserve", "restoration", "extinction",
        "recovery plan", "biodiversity loss", "no-take", "fishing closure",
        "habitat restoration", "reintroduction", "captive breeding", "species at risk",
        "protected species", "critical habitat", "conservation planning", "rewilding",
    ]),
    T("gear", "捕捞技术与兼捕", "Fishing gear & bycatch", [
        "fishing gear", "gear selectivity", "!trawl", "gillnet", "gill net", "longline",
        "purse seine", "!seine!", "!pot!", "!trap!", "bycatch", "discard", "ghost gear",
        "fishing effort", "!cpue!", "catch per unit effort", "!vms!", "ais data",
        "electrofish", "!fyke!", "codend", "mesh size", "selectivity curve",
        "depredation", "unreported catch", "fishing practice", "gear type",
    ]),
    T("econ", "经济与社会政策", "Economics & policy", [
        "economic", "economics", "market", "!price!", "profit", "revenue", "livelihood",
        "income", "small-scale fisher", "artisanal", "governance", "policy", "regulation",
        "subsid", "!iuu!", "illegal fishing", "co-management", "stakeholder",
        "institution", "consumer", "willingness to pay", "certification", "ecolabel",
        "!msc!", "supply chain", "blue economy", "employment", "fisherfolk",
        "fisher folk", "gender", "community-based", "trade", "import", "export",
        "legislation", "!law!", "legal", "food security", "fishery law", "fishing rights",
        "conflict", "capacity building", "extension service",
    ]),
    T("process", "加工品质与食品", "Processing, quality & food", [
        "!fillet", "processing", "!quality!", "texture", "shelf life", "!storage!",
        "freshness", "spoilage", "smoking", "!drying", "canning", "by-product",
        "byproduct", "!gelatin", "hydrolysat", "!surimi", "sensory", "proximate composition",
        "food safety", "histamine", "biogenic amine", "nutritional composition",
        "value-added", "waste valorization", "!proximate", "cooking", "frozen",
        "lipid oxidation", "quality index", "!preservation",
    ]),
    T("review", "综述与元分析", "Review & meta-analysis", [
        "!review!", "!a review", "systematic review", "meta-analysis", "meta analysis",
        "!overview!", "research agenda", "state of the art", "synthesis of",
        "perspective", "bibliometric", "scoping review", "literature review",
    ]),

    # ==================== 研究鱼种 ====================
    S("salmon", "鲑鳟鱼类", "Salmon & trout", [
        "atlantic salmon", "!salmo salar", "!oncorhynchus", "rainbow trout",
        "chinook salmon", "chum salmon", "coho salmon", "sockeye", "pink salmon",
        "brown trout", "!salmo trutta", "salmonid", "!salvelinus", "!salmo!",
        "!trout", "!salmon",
    ]),
    S("cod", "鳕鱼类", "Cod & gadoids", [
        "atlantic cod", "!gadus morhua", "pacific cod", "!gadus", "walleye pollock",
        "!gadus chalcogrammus", "haddock", "!melanogrammus", "hake", "!merluccius",
        "!saithe", "!pollachius", "gadoid", "!eleginus",
    ]),
    S("tuna", "金枪鱼与鲭类", "Tuna & mackerels", [
        "!tuna", "!thunnus", "bluefin", "yellowfin", "skipjack", "!katsuwonus",
        "!mackerel", "!scomber", "!sarda", "!bonito", "!xiphias", "swordfish",
        "!istiophorus", "!albacore", "bigeye",
    ]),
    S("tilapia", "罗非鱼类", "Tilapia", [
        "!tilapia", "!oreochromis", "nile tilapia", "!sarotherodon", "!coptodon",
    ]),
    S("carp", "鲤科鱼类", "Carps & cyprinids", [
        "grass carp", "!ctenopharyngodon", "silver carp", "bighead carp",
        "!hypophthalmichthys", "common carp", "!cyprinus", "crucian carp", "!carassius",
        "!cyprinid", "!mylopharyngodon", "!barbonymus", "!cirrhinus", "!catla",
        "!labeo", "!rohu", "!schizothorax", "!danio",
    ]),
    S("croaker", "黄鱼与石首鱼类", "Croakers & sciaenids", [
        "large yellow croaker", "!larimichthys", "small yellow croaker", "!larimichthys polyactis",
        "!croaker", "!sciaenid", "!pseudosciaena", "!nia albiflora", "!collichthys",
        "!miichthys", "!sciaenops", "!mulloway", "!argyrosomus",
    ]),
    S("seabass", "鲈鱼与石斑鱼", "Seabass, bream & grouper", [
        "sea bass", "seabass", "!lateolabrax", "!dicentrarchus", "!morone",
        "!grouper", "!epinephelus", "!mycteroperca", "sea bream", "seabream",
        "!sparus aurata", "!sparidae", "!pagrus", "!acanthopagrus", "!opsanus",
        "!lates", "!barramundi", "!lates calcarifer",
    ]),
    S("flatfish", "鲆鲽类", "Flatfish", [
        "!flatfish", "japanese flounder", "!paralichthys", "!scophthalmus",
        "!hippoglossus", "halibut", "!pleuronectes", "!platichthys", "!solea",
        "!sole!", "!turbot", "!psetta", "!verasper", "!cynoglossus",
    ]),
    S("shrimp", "虾类", "Shrimp & prawns", [
        "!shrimp", "!prawn", "!penaeus", "!litopenaeus", "whiteleg shrimp",
        "!metapenaeus", "!macrobrachium", "!crangon", "!pandalus", "!artemia",
        "!euphausia", "!krill", "!mysid",
    ]),
    S("crab", "蟹类", "Crabs", [
        "!crab", "!portunus", "!eriocheir", "!scylla", "!carcinus", "!callinectes",
        "!chionoecetes", "!paralithodes", "!cancer magister", "!hemigrapsus",
        "mud crab", "swimming crab", "!menippe",
    ]),
    S("shellfish", "贝类", "Shellfish & molluscs", [
        "!oyster", "!crassostrea", "!mussel", "!mytilus", "!scallop", "!pecten",
        "!patinopecten", "!argopecten", "!clam!", "!ruditapes", "!mercenaria",
        "!anadara", "!sinonovacula", "!abalone", "!haliotis", "!bivalve",
        "!gastropod", "!cockle", "!mollusc", "!mollusk", "!mactra", "!scapharca",
    ]),
    S("cephalo", "头足类", "Cephalopods", [
        "!squid", "!octopus", "cuttlefish", "!cephalopod", "!illex", "!dosidicus",
        "!loligo", "!sepia", "!octopod", "!nautilus",
    ]),
    S("echino", "海参与海胆", "Sea cucumber & urchin", [
        "sea cucumber", "!apostichopus", "!holothuria", "!stichopus", "sea urchin",
        "!strongylocentrotus", "!echinometra", "!lytechinus", "!paracentrotus",
    ]),
    S("seaweed", "藻类与海藻", "Seaweed & algae", [
        "!seaweed", "!kelp", "!saccharina", "!laminaria", "!undaria", "!pyropia",
        "!porphyra", "!nori", "!gracilaria", "!eucheuma", "!sargassum", "!ulva",
        "macroalg", "!microalg", "!chlorella", "!nannochloropsis", "!spirulina",
        "!diatom", "!dinoflagellate", "!harmful algal", "!red tide", "!agar",
    ]),
    S("carchar", "鲨鱼与鳐类", "Sharks & rays", [
        "!shark", "!ray!", "!rays!", "!skate", "!elasmobranch", "!carcharhinus",
        "!squalus", "!prionace", "!raja", "!dasyatis", "!rhynchobatus", "!manta",
        "!whale shark", "!rhincodon", "!galeocerdo", "!mustelus", "!sphyrna",
    ]),
    S("marine-mammal", "鲸豚与海兽", "Marine mammals", [
        "!whale", "!dolphin", "!porpoise", "!cetacean", "!tursiops", "!phocoena",
        "!delphinus", "!balaenoptera", "!megaptera", "!seal!", "!phoca", "!otariid",
        "!sea lion", "!dugong", "!manatee", "!pinniped", "!orca", "!sotalia",
    ]),
    S("turtle-bird", "海龟与海鸟", "Sea turtles & seabirds", [
        "sea turtle", "!chelonia", "!caretta", "!dermochelys", "!lepidochelys",
        "!seabird", "!albatross", "!penguin", "!shearwater", "!petrel", "!cormorant",
        "!gull!", "!tern!",
    ]),
    S("eel", "鳗鲡与鲟类", "Eels & sturgeons", [
        "!eel!", "!eels!", "!anguilla", "japanese eel", "!conger", "!sturgeon",
        "!acipenser", "!huso", "!paddlefish",
    ]),
    S("catfish", "鲶形目鱼类", "Catfishes", [
        "!catfish", "!ictalurus", "!silurus", "!clarias", "!pangasius",
        "!pangasianodon", "!pseudobagrus", "!pelteobagrus", "!leiocassis",
    ]),
    S("freshwater-other", "其他淡水鱼", "Other freshwater fish", [
        "!perch", "!perca", "!sander", "!pikeperch", "!esox", "!pike!",
        "!zander", "!mandarin fish", "!siniperca", "!loach", "!misgurnus",
        "!cobitis", "!puffer", "!takifugu", "!tetraodon", "!mugil", "!liza",
        "!mullet", "!chanos", "!milkfish", "!snakehead", "!channa", "!climbing perch",
        "!anabas", "!betta",
    ]),
    S("forage", "饵料鱼类", "Forage fish", [
        "!herring", "!clupea", "!sardine", "!sardinops", "!sardinella",
        "!anchovy", "!engraulis", "!sprat", "!sprattus", "!capelin", "!mallotus",
        "!sand lance", "!ammodytes", "!menhaden", "!brevoortia", "!forage fish",
    ]),
    S("scorpion", "鲉形目与底栖鱼", "Rockfish & demersal fish", [
        "!rockfish", "!sebastes", "!scorpionfish", "!sebastolobus", "!redfish",
        "!lingcod", "!ophiodon", "!sablefish", "!anoplopoma", "!grenadier",
        "!macrourus", "!coryphaenoides", "!tilefish", "!lopholatilus",
    ]),
    S("jelly", "水母与浮游动物", "Jellyfish & zooplankton", [
        "!jellyfish", "!scyphozoa", "!aurelia", "!nemopilema", "!ctenophore",
        "!copepod", "!calanus", "!amphipod", "!gammarus", "!daphnia", "!rotifer",
        "!bivalve larvae", "!barnacle",
    ]),
    S("cobia", "鲹科与军曹鱼", "Cobia & jacks", [
        "!cobia", "!rachycentron", "!seriola", "!yellowtail", "!trachinotus",
        "!pompano", "!caranx", "!jack!", "!amberjack",
    ]),

    # ==================== 海域区域 ====================
    G("bs", "渤海", "Bohai Sea", ["bohai"]),
    G("ys", "黄海", "Yellow Sea", ["yellow sea", "!huanghai"]),
    G("ecs", "东海", "East China Sea", ["east china sea", "!donghai"]),
    G("scs", "南海", "South China Sea", ["south china sea", "!nanhai", "beibu gulf",
                                         "gulf of tonkin", "taiwan strait"]),
    G("china", "中国近海与内陆", "China waters", [
        "china", "chinese", "yangtze", "changjiang", "yellow river", "zhujiang",
        "pearl river", "taihu", "poyang", "dongting", "three gorges", "!prc!",
    ]),
    G("npac", "北太平洋", "North Pacific", [
        "north pacific", "northeast pacific", "northwest pacific", "bering sea",
        "gulf of alaska", "aleutian", "kuroshio", "oyashio", "california current",
        "pacific coast", "japan sea", "sea of japan", "sea of okhotsk",
    ]),
    G("natl", "北大西洋", "North Atlantic", [
        "north atlantic", "northeast atlantic", "northwest atlantic", "north sea",
        "barents sea", "iceland", "labrador", "newfoundland", "gulf of maine",
        "georges bank", "scotian shelf", "flemish cap", "irish sea", "celtic sea",
        "bay of biscay", "gulf stream", "sargasso",
    ]),
    G("med", "地中海与黑海", "Mediterranean & Black Sea", [
        "mediterranean", "adriatic", "aegean", "black sea", "!tyrrhenian",
        "!ionian", "levantine", "!aegean sea",
    ]),
    G("baltic", "波罗的海", "Baltic Sea", ["baltic"]),
    G("carib", "加勒比与墨西哥湾", "Caribbean & Gulf of Mexico", [
        "caribbean", "gulf of mexico", "!florida keys", "!bahamas", "!antilles",
        "!sargassum", "!belize",
    ]),
    G("southam", "南美海域", "South America waters", [
        "brazil", "!patagonia", "argentina", "chile", "peru", "humboldt",
        "!amazon", "!uruguay", "!galapagos", "!ecuador",
    ]),
    G("africa", "非洲海域", "Africa waters", [
        "africa", "!kenya", "!tanzania", "!mozambique", "!nigeria", "!ghana",
        "!senegal", "!morocco", "!egypt", "!madagascar", "!benguela", "!lake victoria",
    ]),
    G("india", "印度洋与南亚", "Indian Ocean & South Asia", [
        "indian ocean", "arabian sea", "bay of bengal", "!india", "!bangladesh",
        "!sri lanka", "!pakistan", "!maldives", "!red sea", "!persian gulf",
        "!oman", "!somali",
    ]),
    G("seasia", "东南亚与西太", "Southeast Asia & Western Pacific", [
        "southeast asia", "!mekong", "!indonesia", "!vietnam", "!thailand",
        "!philippines", "!malaysia", "!myanmar", "!coral triangle", "!borneo",
        "!java sea", "!sulu sea", "!great barrier reef", "!australia", "!queensland",
        "!new zealand", "!papua",
    ]),
    G("polar", "极地与南大洋", "Polar & Southern Ocean", [
        "antarctic", "southern ocean", "!arctic!", "arctic ocean", "!svalbard",
        "!greenland", "!chukchi", "!beaufort", "!ross sea", "!weddell", "!sub-antarctic",
        "!kerguelen", "!barents",
    ]),
    G("freshwater", "淡水与湖泊河流", "Freshwater, lakes & rivers", [
        "lake!", "!lakes", "reservoir", "river basin", "!stream!", "!streams",
        "freshwater", "!great lakes", "!danube", "!mississippi", "!mekong river",
        "!floodplain", "!backwater",
    ]),
    G("global", "全球/多区域", "Global & multi-region", [
        "global", "worldwide", "!global scale", "cross-national", "!multi-region",
        "!international", "!large-scale",
    ]),

    # ==================== 方法手段 ====================
    M("edna", "环境DNA", "eDNA & metabarcoding", [
        "environmental dna", "!edna!", "metabarcoding", "!barcod", "!ddpcr",
        "!qpcr!", "!pcr!", "amplicon", "high-throughput sequencing", "!ngs!",
    ]),
    M("isotope", "稳定同位素", "Stable isotopes", [
        "stable isotope", "!δ13c!", "!δ15n!", "!d13c!", "!d15n!", "!carbon isotope",
        "!nitrogen isotope", "isotopic niche", "!trophic position",
    ]),
    M("otolith", "耳石与硬组织", "Otolith & hard parts", [
        "!otolith", "!microchemistr", "!sclerochronolog", "!statolith", "!vertebra",
        "!scale circul", "!bomb radiocarbon", "!trace element",
    ]),
    M("acoustic", "声学与遥测", "Acoustics & telemetry", [
        "acoustic telemetry", "!hydroacoustic", "!echosounder", "!echo sounder",
        "!sonar", "!acoustic survey", "!biotelemetry", "!satellite tag",
        "!pop-up archival", "!data storage tag", "!passive acoustic monitoring",
        "!archival tag", "!ultrasonic",
    ]),
    M("remote", "遥感与空间分析", "Remote sensing & GIS", [
        "remote sensing", "!satellite imagery", "!modis!", "!landsat", "!sentinel-2",
        "!viirs!", "!ocean colour", "!ocean color", "!gis!", "!geographic information",
        "!spatial analysis", "!geostatistic", "!sea surface height", "!chlorophyll-a",
    ]),
    M("ml", "机器学习与AI", "Machine learning & AI", [
        "machine learning", "deep learning", "neural network", "random forest",
        "!xgboost", "!gradient boosting", "!support vector", "!convolutional",
        "artificial intelligence", "!transformer model", "!computer vision",
        "!image recognition", "!object detection", "!yolo", "transfer learning",
        "!segment", "!detection model", "!large language model", "!llm!",
    ]),
    M("model", "生态与渔业模型", "Ecosystem & fishery models", [
        "!ecopath", "!ecosim", "!atlantis", "ecosystem model", "!osmose!",
        "individual-based model", "!ibm!", "!stock synthesis", "!ss3!",
        "!state-space model", "!simulation model", "!coupled model", "!scenario analysis",
        "!bioenergetic", "!dynamic energy budget", "!deployment model",
    ]),
    M("sdm", "分布模型与栖息地评价", "Species distribution models", [
        "species distribution model", "!sdm!", "!maxent", "habitat suitability model",
        "!biomod", "!ensemble model", "!ecological niche model", "!enm!",
        "!boosted regression", "!glm!", "!gam!", "!gwr!", "!random forest model",
    ]),
    M("ocean-model", "海洋数值模拟", "Ocean numerical modelling", [
        "!roms!", "!fvcom!", "!hycom!", "!mitgcm!", "!nemo!", "hydrodynamic model",
        "ocean model", "!circulation model", "!particle tracking", "!lagrangian",
        "!regional ocean model", "!cmip", "!downscal",
    ]),
    M("experiment", "受控实验", "Controlled experiments", [
        "!mesocosm", "!laboratory experiment", "!aquarium experiment", "!common garden",
        "!controlled experiment", "!microcosm", "!rearing experiment", "!dose-response",
        "!transplant experiment", "!field experiment", "!enclosure experiment",
    ]),
    M("survey", "调查与问卷", "Surveys & interviews", [
        "questionnaire", "!interview", "!survey data", "!participatory",
        "!fisher logbook", "!logbook", "!onboard observer", "!observer program",
        "!focus group", "!stated preference", "!contingent valuation", "!likert",
    ]),
    M("monitor", "监测与采样", "Monitoring & sampling", [
        "!monitoring", "!sampling", "long-term data", "!census", "!field survey",
        "!time series data", "!survey data", "!catch data", "!fishery-dependent",
        "!index of abundance", "!seasonal sampling", "!annual survey",
    ]),
    M("stat", "统计建模", "Statistical modelling", [
        "!bayesian", "!glmm", "!mixed model", "!hierarchical model", "!mark-recapture",
        "!capture-recapture", "!survival analysis", "!multivariate analysis",
        "!ordination", "!nmds!", "!pca!", "!structural equation", "!time series",
        "!arima", "!bootstrap", "!monte carlo", "!meta-regression",
        "!gam!", "!glm!", "!regression model", "!linear model", "!anova!",
        "!ordination", "!cluster analysis", "!machine learning model",
    ]),
]

# 高影响力期刊（精确匹配，避免 "Fisheries Science" 被 "science" 误判）
HIGH_IMPACT_EXACT = {
    "nature", "science", "pnas",
    "proceedings of the national academy of sciences",
    "science advances", "science immunology", "science robotics",
    "nature climate change", "nature ecology & evolution", "nature sustainability",
    "nature communications", "nature food", "nature water", "nature plants",
    "nature reviews earth & environment", "one earth", "current biology",
    "nature geoscience", "nature human behaviour", "pnas nexus",
}
HIGH_IMPACT_PREFIX = ("nature ", "trends in ecology", "annual review of marine")

REVIEW_TITLE = re.compile(
    r"\b(review|meta-?analysis|overview|perspective|synthesis|state of the art|"
    r"a framework|research agenda|progress and|advances in|lessons from)\b",
    re.IGNORECASE,
)


def compile_pattern(p: str):
    """以 ! 开头表示整词匹配，其余为子串匹配；统一小写"""
    if p.startswith("!"):
        raw = p[1:].strip("!")
        return re.compile(r"\b" + re.escape(raw.lower()), re.IGNORECASE)
    return re.compile(re.escape(p.lower()), re.IGNORECASE)


for _r in RULES:
    _r["compiled"] = [compile_pattern(p) for p in _r["pats"]]


def is_high_impact(journal: str) -> bool:
    jl = re.sub(r"\s+", " ", (journal or "").lower().strip())
    if not jl:
        return False
    if jl in HIGH_IMPACT_EXACT:
        return True
    return jl.startswith(HIGH_IMPACT_PREFIX)


TAG_RE = re.compile(r"<[^>]+>")
DASH_RE = re.compile(r"[\u2010-\u2015\u2212]")
WS_RE = re.compile(r"\s+")


def normalize_text(raw: str) -> str:
    """去掉 Crossref 返回的 JATS 标签、HTML 实体并压平空白"""
    if not raw:
        return ""
    s = htmllib.unescape(raw)
    s = TAG_RE.sub(" ", s)
    s = DASH_RE.sub("-", s)
    s = s.replace("\u00a0", " ")
    return WS_RE.sub(" ", s).strip()


def match_any(text: str, keys) -> str:
    tl = (text or "").lower()
    for k in keys:
        if k in tl:
            return k
    return ""


def is_trusted_journal(journal: str) -> bool:
    jl = re.sub(r"\s+", " ", (journal or "").lower()).strip()
    return bool(jl) and any(k in jl for k in TRUSTED_JOURNAL_PATS)


def is_medical_journal(journal: str) -> bool:
    jl = re.sub(r"\s+", " ", (journal or "").lower()).strip()
    return bool(jl) and any(k in jl for k in MEDICAL_JOURNAL_PATS)


def assess_relevance(paper: dict, tags: dict) -> tuple:
    """判定论文是否属于渔业科学范畴，返回 (是否相关, 判定依据)

    判定顺序（越前优先级越高）：
      1. 渔业/水产专业期刊 → 免检
      2. 医学/临床类期刊 → 无关（"误吞鱼刺致胃穿孔"不是渔业研究）
      3. STRICT 领域标志词（海洋工程、航运、管理、昆虫）→ 无关
      4. 标题是仿生机器人研究 → 无关
      5. 鱼种标签 → 相关
      6. 渔业核心主题（养殖 / 种群评估）→ 相关
      7. SOFT 词（临床、材料、食品工程）→ 无关
      8. 正文出现水生生物或渔业活动词 → 相关
      9. 其余 → 无关
    """
    if is_trusted_journal(paper.get("journal", "")):
        return True, "专业期刊"

    if is_medical_journal(paper.get("journal", "")):
        return False, "医学期刊"

    title = paper.get("title", "")
    abstract = paper.get("abstract", "")

    hit = match_any(title, OFF_TOPIC_STRICT) or match_any(abstract, OFF_TOPIC_STRICT)
    if hit:
        return False, f"无关领域:{hit}"

    hit = match_any(title, ROBOTIC)
    if hit:
        return False, f"仿生机器人:{hit}"

    if tags.get("species"):
        return True, "鱼种:" + ",".join(tags["species"][:2])

    if CORE_THEMES & set(tags.get("theme", [])):
        core = sorted(CORE_THEMES & set(tags["theme"]))
        return True, "核心主题:" + ",".join(core)

    hit = match_any(title, OFF_TOPIC_SOFT) or match_any(abstract, OFF_TOPIC_SOFT)
    if hit:
        return False, f"无关领域:{hit}"

    text = (title + " " + abstract).lower()
    n = len(STRONG_FISH.findall(text))
    if not n:
        return False, "无渔业证据"

    # 标题里点到水生生物，或正文反复出现（≥2 次）才算自证。
    # 只看 1 次会被"社论标题引用一句 fish""政策论文顺带提一句渔业"这类噪声骗过。
    if n >= 2 or STRONG_FISH.search(title):
        return True, f"关键词×{n}"

    return False, "无渔业证据"


def score_paper(title: str, abstract: str) -> dict:
    """返回 {dim: [(score, rule), ...]}，仅保留过阈值的项"""
    hits = defaultdict(list)
    for rule in RULES:
        score = 0
        for rx in rule["compiled"]:
            n_title = len(rx.findall(title))
            if n_title:
                score += n_title * TITLE_WEIGHT
            n_abs = len(rx.findall(abstract))
            if n_abs:
                score += min(n_abs, ABS_MAX_HITS) * ABS_WEIGHT
        if score >= MIN_SCORE[rule["dim"]]:
            hits[rule["dim"]].append((score, rule))
    return hits


def tag_paper(paper: dict) -> dict:
    title = normalize_text(paper.get("title", ""))
    abstract = normalize_text(paper.get("abstract", ""))
    paper["title"] = title
    paper["abstract"] = abstract
    paper["authors"] = normalize_text(paper.get("authors", ""))
    paper["journal"] = normalize_text(paper.get("journal", ""))

    hits = score_paper(title, abstract)
    tags = {}
    for dim, cap in CAP.items():
        items = sorted(hits.get(dim, []), key=lambda x: (-x[0], x[1]["zh"]))[:cap]
        tags[dim] = [r["id"] for _, r in items]

    if not tags.get("theme"):
        tags["theme"] = ["misc"]

    paper["tags"] = tags
    paper["is_review"] = bool(REVIEW_TITLE.search(title))
    paper["high_impact"] = is_high_impact(paper.get("journal", ""))
    relevant, why = assess_relevance(paper, tags)
    paper["off_topic"] = not relevant
    paper["rel_reason"] = why
    return paper


def lexicon() -> list:
    """导出标签字典（供前端渲染名称与配色）"""
    out = [{"dim": "theme", "id": "misc", "zh": "综合/其他", "en": "Miscellaneous"}]
    for r in RULES:
        out.append({"dim": r["dim"], "id": r["id"], "zh": r["zh"], "en": r["en"]})
    return out


def main():
    force = "--force" in sys.argv
    if not DATA_FILE.exists():
        print(f"❌ 数据文件不存在: {DATA_FILE}")
        sys.exit(1)

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    papers = data.get("papers", [])
    # 没有标签的、或旧版本没留下判定依据的，都要重新过一遍
    todo = papers if force else [p for p in papers if not p.get("tags") or "rel_reason" not in p]
    print(f"🏷️  待打标论文: {len(todo)} / {len(papers)}")

    stat = defaultdict(int)
    for i, p in enumerate(todo, 1):
        tag_paper(p)
        for dim, ids in p["tags"].items():
            for tid in ids:
                stat[f"{dim}:{tid}"] += 1
        if i % 50 == 0 or i == len(todo):
            print(f"   {i}/{len(todo)}")

    data["papers"] = papers
    data["tag_lexicon"] = lexicon()
    data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 打标完成，写入 {DATA_FILE}")
    top = sorted(stat.items(), key=lambda x: -x[1])[:12]
    for k, v in top:
        print(f"   {k:28s} {v}")


if __name__ == "__main__":
    main()
