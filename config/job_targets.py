"""
Keyword taxonomy for classifying job postings.

Tier 1 — C++ / low-latency systems (highest priority)
Tier 2 — Low-level / infrastructure / embedded
Tier 3 — Graphics / GPU / simulation
Tier 4 — General SWE (lowest priority, still relevant)
"""

# ──────────────────────────────────────────────
# Tier 1: C++ systems / high-frequency / finance
# ──────────────────────────────────────────────
TIER1_KEYWORDS = [
    "c++",
    "c++ engineer",
    "c++ developer",
    "c++17",
    "c++20",
    "low latency",
    "low-latency",
    "high frequency",
    "high-frequency trading",
    "hft",
    "quantitative",
    "systems engineer",
    "systems programmer",
    "systems software",
    "kernel",
    "stl",
    "template metaprogramming",
    "lock-free",
    "lock free",
    "memory management",
    "real-time systems",
    "real time systems",
    "trading systems",
    "market data",
    "order management",
    "execution engine",
    "matching engine",
    "fpga",
    "simd",
    "intrinsics",
    "performance optimization",
    "cache efficiency",
    "numa",
    "tcp/ip stack",
    "kernel bypass",
    "dpdk",
    "rdma",
]

# ──────────────────────────────────────────────
# Tier 2: Low-level / infrastructure / embedded
# ──────────────────────────────────────────────
TIER2_KEYWORDS = [
    "systems programming",
    "embedded systems",
    "firmware",
    "driver development",
    "linux kernel",
    "operating systems",
    "distributed systems",
    "infrastructure engineer",
    "platform engineer",
    "compiler",
    "llvm",
    "jit",
    "virtual machine",
    "hypervisor",
    "storage systems",
    "database internals",
    "network stack",
    "protocol implementation",
    "rust",
    "assembly",
    "x86",
    "arm",
    "risc-v",
    "bare metal",
    "rtos",
    "device driver",
    "bsp",
    "bootloader",
]

# ──────────────────────────────────────────────
# Tier 3: Graphics / GPU / simulation
# ──────────────────────────────────────────────
TIER3_KEYWORDS = [
    "graphics engineer",
    "rendering engineer",
    "gpu engineer",
    "opengl",
    "vulkan",
    "directx",
    "metal",
    "cuda",
    "opencl",
    "shader",
    "ray tracing",
    "physically based rendering",
    "pbr",
    "game engine",
    "unreal engine",
    "unity",
    "physics simulation",
    "simulation engineer",
    "cfd",
    "finite element",
    "scientific computing",
    "hpc",
    "high performance computing",
    "mpi",
    "openmp",
    "parallel computing",
    "3d graphics",
    "real-time rendering",
    "visual effects",
    "vfx",
]

# ──────────────────────────────────────────────
# Tier 4: General SWE (still relevant)
# ──────────────────────────────────────────────
TIER4_KEYWORDS = [
    "software engineer",
    "software developer",
    "backend engineer",
    "backend developer",
    "full stack",
    "fullstack",
    "senior engineer",
    "staff engineer",
    "principal engineer",
    "golang",
    "go developer",
    "java",
    "python",
    "distributed computing",
    "microservices",
    "kubernetes",
    "cloud",
    "aws",
    "gcp",
    "azure",
]

# ──────────────────────────────────────────────
# NYC location patterns
# ──────────────────────────────────────────────
NYC_LOCATION_PATTERNS = [
    "new york",
    "new york city",
    "nyc",
    "manhattan",
    "brooklyn",
    "queens",
    "bronx",
    "staten island",
    "jersey city",
    "hoboken",
    "remote",         # include remote — can apply from NYC
    "hybrid",
    "new york, ny",
    "ny, usa",
]

# ──────────────────────────────────────────────
# Hard exclusion keywords (skip these jobs)
# ──────────────────────────────────────────────
EXCLUSION_KEYWORDS = [
    "javascript only",
    "frontend only",
    "react developer",
    "angular developer",
    "vue developer",
    "ios developer",
    "android developer",
    "mobile developer",
    "qa engineer",
    "test engineer",
    "sdet",
    "salesforce",
    "sap",
    "data analyst",
    "business analyst",
    "product manager",
    "project manager",
    "scrum master",
    "devops only",
    "site reliability",
    "sre only",
    "security engineer",
    "marketing",
    "sales engineer",
    "solutions engineer",
    "customer success",
    "technical support",
    "help desk",
    "clearance required",
    "us citizenship required",
    "top secret",
    "ts/sci",
]

# ──────────────────────────────────────────────
# Search queries per source
# ──────────────────────────────────────────────
SEARCH_QUERIES = {
    "linkedin": [
        "C++ software engineer New York",
        "systems software engineer NYC",
        "low latency C++ engineer New York",
        "HFT software engineer New York",
        "graphics engineer New York",
    ],
    "indeed": [
        "C++ engineer New York",
        "systems programmer NYC",
        "low latency engineer New York",
    ],
    "glassdoor": [
        "C++ engineer New York",
        "systems software engineer NYC",
    ],
    "builtin": [
        "c++",
        "systems engineer",
        "graphics engineer",
    ],
}

# ATS domain patterns
ATS_PATTERNS = {
    "greenhouse": ["greenhouse.io", "boards.greenhouse.io"],
    "lever": ["lever.co", "jobs.lever.co"],
    "workday": ["myworkdayjobs.com", "workday.com"],
    "icims": ["icims.com", "careers."],
    "taleo": ["taleo.net"],
    "smartrecruiters": ["smartrecruiters.com"],
}
