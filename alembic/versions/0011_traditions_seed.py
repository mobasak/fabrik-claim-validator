"""traditions seed — 12 peer-equal traditions (§5.2)

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-03

Seeds the 11 core traditions + Canadian NHPID per plan §5.2.
Parent-tradition refs: kampo/dong_y -> tcm, tpm -> unani.
"""
import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


SEED_ROWS = [
    # (code, name_en, name_native, primary_authority_url, corpus_size,
    #  ingestion_status, evidence_weight_class, primary_lang,
    #  parent_tradition_id, independence_weight, evidence_tier_map_json)
    ("western_rct", "Western RCT", None, "https://pubmed.ncbi.nlm.nih.gov/",
     9999999, "complete", "clinical_research", "en", None, 1.0,
     '{"A":"meta_analysis_or_large_rct","B":"single_rct","C":"observational"}'),
    ("tcm", "Chinese (TCM)", "中医", "https://herb.ac.cn/",
     1500, "pending", "regulatory_pharmacopoeia", "zh", None, 1.0,
     '{"A":"pharmacopoeial_monograph","B":"academic_consensus","C":"classical_text"}'),
    ("kampo", "Japanese (Kampo)", "漢方", "https://www.pmda.go.jp/",
     1500, "pending", "regulatory_pharmacopoeia", "ja", "tcm", 0.4,
     '{"A":"jp18_monograph","B":"kampo_society_consensus","C":"clinical_report"}'),
    ("korean", "Korean (KP)", "한국약전", "https://nedrug.mfds.go.kr/",
     600, "pending", "regulatory_pharmacopoeia", "ko", None, 1.0,
     '{"A":"kp12_monograph","B":"academic_consensus","C":"clinical_report"}'),
    ("ayush", "Indian (Ayurveda)", "आयुष", "http://ayushportal.nic.in/",
     800, "pending", "regulatory_pharmacopoeia", "sa", None, 1.0,
     '{"A":"api_monograph","B":"ccras_consensus","C":"classical_text"}'),
    ("unani", "Indian (Unani-Tibb)", "يونانى", "https://ccrum.res.in/",
     250, "pending", "regulatory_pharmacopoeia", "ar", None, 1.0,
     '{"A":"upi_monograph","B":"ccrum_consensus","C":"classical_text"}'),
    ("tpm", "Persian (TPM)", "طب سنّتی ایرانی", "https://research.tums.ac.ir/",
     400, "pending", "regulatory_pharmacopoeia", "fa", "unani", 0.4,
     '{"A":"iran_moh_monograph","B":"academic_consensus","C":"classical_text"}'),
    ("rp_xv", "Russian phytotherapy", "Российская фармакопея",
     "https://femb.ru/femb/pharmacopea.php",
     250, "pending", "regulatory_pharmacopoeia", "ru", None, 1.0,
     '{"A":"rp_xv_monograph","B":"academic_consensus","C":"clinical_report"}'),
    ("ema_hmpc", "German/EU phytomedicine", "EMA HMPC",
     "https://www.ema.europa.eu/en/medicines/herbal",
     250, "pending", "regulatory_pharmacopoeia", "en", None, 1.0,
     '{"A":"hmpc_well_established","B":"hmpc_traditional_use","C":"in_progress"}'),
    ("dong_y", "Vietnamese (Đông y)", "Đông y", "http://www.nimm.org.vn/",
     150, "pending", "regulatory_pharmacopoeia", "vi", "tcm", 0.4,
     '{"A":"nimm_monograph","B":"academic_consensus","C":"folk_record"}'),
    ("ttm", "Thai TTM", "แพทย์แผนไทย", "https://thaicam.go.th/",
     200, "pending", "regulatory_pharmacopoeia", "th", None, 1.0,
     '{"A":"thp_monograph","B":"dtam_consensus","C":"folk_record"}'),
    ("nhpid", "Canadian NHPID", None, "https://hpr-rps.hres.ca/",
     800, "pending", "regulatory_pharmacopoeia", "en", None, 1.0,
     '{"A":"nhpid_monograph","B":"licensed_product","C":"applicant_claim"}'),
]


INSERT_STMT = sa.text(
    """
    INSERT INTO traditions (
        code, name_en, name_native, primary_authority_url,
        monograph_corpus_size, ingestion_status, evidence_weight_class,
        primary_lang, parent_tradition_id, independence_weight,
        evidence_tier_map
    ) VALUES (
        :code, :name_en, :name_native, :url,
        :corpus, :status, :weight_class,
        :lang, :parent, :indep,
        CAST(:tier_map AS JSONB)
    )
    ON CONFLICT (code) DO NOTHING;
    """
)


def upgrade() -> None:
    # Insert parents first (NULL parent_tradition_id) to satisfy FK,
    # then children.
    parents = [r for r in SEED_ROWS if r[8] is None]
    children = [r for r in SEED_ROWS if r[8] is not None]
    bind = op.get_bind()
    for row in parents + children:
        bind.execute(
            INSERT_STMT,
            {
                "code": row[0],
                "name_en": row[1],
                "name_native": row[2],
                "url": row[3],
                "corpus": row[4],
                "status": row[5],
                "weight_class": row[6],
                "lang": row[7],
                "parent": row[8],
                "indep": row[9],
                "tier_map": row[10],
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    codes = [r[0] for r in SEED_ROWS]
    bind.execute(
        sa.text("DELETE FROM traditions WHERE code = ANY(:codes)"),
        {"codes": codes},
    )
