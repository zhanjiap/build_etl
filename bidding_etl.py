#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
招投标文件元数据提取 ETL 脚本
=================================
单文件版 —— 自动安装依赖，直接运行即可。
环境要求: Python 3.8, Linux / macOS / WSL / Windows
"""

import subprocess
import sys as _sys

# ── 自动安装缺失的依赖 ────────────────────────────────────────────────────
_REQUIRED_PACKAGES = [
    ("pandas", "pandas>=1.2,<2.0"),
    ("trino", "trino>=0.327,<1.0"),
    ("PyPDF2", "PyPDF2>=2.0,<3.0"),
    ("docx", "python-docx>=0.8,<1.0"),
]

# PyInstaller 打包后跳过自动安装（所有依赖已内置）
if not getattr(_sys, "frozen", False):
    for _import_name, _pip_spec in _REQUIRED_PACKAGES:
        try:
            __import__(_import_name)
        except ImportError:
            print(f"[安装依赖] 正在安装 {_pip_spec} ...")
            subprocess.check_call(
                [_sys.executable, "-m", "pip", "install", _pip_spec, "-q"]
            )

import os
import uuid
import logging
import multiprocessing as mp
from typing import List, Tuple

import pandas as pd
from trino.auth import BasicAuthentication
from trino.dbapi import connect
import PyPDF2
from docx import Document

import warnings
warnings.filterwarnings("ignore")

# ── 日志配置 ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 数据库配置 ────────────────────────────────────────────────────────────
TRINO_CONFIG = {
    "host": "10.96.74.17",
    "port": 30001,
    "user": "audit_dq",
    "catalog": "ice",
    "schema": "audit_dw",
    "password": "AuditDq@98367",
    "http_scheme": "https",
    "verify": False,
}

# ── SQL 模板 ──────────────────────────────────────────────────────────────
BIDDING_SQL = {
    "d_procurement_bidding_files": """
select file_name, file_path, attachment_type, bid_header_number,
       date_format(now(), '%Y%m') as data_source
from ice_audit_dw.d_procurement_bidding_files_origin_e
where file_path like concat('%', date_format(now(), '%Y%m'), '%')
  and (lower(file_name) like '%.pdf' or lower(file_name) like '%.doc'
       or lower(file_name) like '%.docx')
  and bid_header_number not in (
      select distinct bid_header_number
      from ice_audit_dw.d_procurement_bidding_files_e
      where data_source = date_format(now(), '%Y%m')
        and bid_header_number is not null
  )
""",
    "d_procurement_bid_files": """
select file_name, file_path, attachment_type, bid_header_number,
       date_format(now(), '%Y%m') as data_source
from ice_audit_dw.d_procurement_bid_files_origin_e
where file_path like concat('%', date_format(now(), '%Y%m'), '%')
  and (lower(file_name) like '%.pdf' or lower(file_name) like '%.doc'
       or lower(file_name) like '%.docx')
  and bid_header_number not in (
      select distinct bid_header_number
      from ice_audit_dw.d_procurement_bid_files_e
      where data_source = date_format(now(), '%Y%m')
        and bid_header_number is not null
  )
""",
}

# ── 实用函数 ──────────────────────────────────────────────────────────────


def clean_nul(s: str) -> str:
    """清洗字符串中的 NUL（\\x00）字符"""
    return s.replace("\x00", "") if isinstance(s, str) else s


# ── 数据库交互 ────────────────────────────────────────────────────────────


def _get_connection():
    """创建 Trino 连接"""
    auth = BasicAuthentication(TRINO_CONFIG["user"], TRINO_CONFIG["password"])
    conn = connect(
        host=TRINO_CONFIG["host"],
        port=TRINO_CONFIG["port"],
        user=TRINO_CONFIG["user"],
        catalog=TRINO_CONFIG["catalog"],
        schema=TRINO_CONFIG["schema"],
        http_scheme=TRINO_CONFIG["http_scheme"],
        auth=auth,
        verify=TRINO_CONFIG["verify"],
    )
    return conn


def get_data(sql: str) -> pd.DataFrame:
    """执行 SQL 并返回结果 DataFrame"""
    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        data = pd.DataFrame(
            rows,
            columns=["file_name", "file_path", "attachment_type",
                     "bid_header_number", "data_source"],
        )
        cur.close()
    finally:
        conn.close()
    logger.info("已获取 %d 条记录", len(data))
    return data


def save_data(data: pd.DataFrame, table: str) -> pd.DataFrame:
    """将处理后的 DataFrame 逐行写入 Trino 目标表"""
    conn = _get_connection()
    cur = conn.cursor()
    saved = 0
    for _, row in data.iterrows():
        try:
            values = (
                str(row["file_name"]).replace("'", "''"),
                str(row["file_path"]).replace("'", "''"),
                str(row["attachment_type"]).replace("'", "''"),
                str(row["bid_header_number"]).replace("'", "''")
                if pd.notna(row["bid_header_number"])
                else "NULL",
                str(row["data_source"]).replace("'", "''"),
                str(row["author"]).replace("'", "''"),
            )

            bid_header_value = (
                f'"{values[3]}"' if values[3] != "NULL" else "NULL"
            )

            insert_sql = f"""
INSERT INTO ice.audit_dw.{table}
    (s_id, file_name, file_path, attachment_type, bid_header_number,
     data_source, author)
VALUES (
    '{uuid.uuid4().hex}',
    '{values[0]}',
    '{values[1]}',
    '{values[2]}',
    {bid_header_value},
    '{values[4]}',
    '{values[5]}'
)
"""
            cur.execute(insert_sql)
            conn.commit()
            saved += 1
        except Exception as e:
            logger.error("插入失败: %s", e)
            continue

    cur.close()
    conn.close()
    logger.info("成功写入 %d / %d 条记录到 %s", saved, len(data), table)
    return data


# ── 文件处理 ──────────────────────────────────────────────────────────────


def get_author(file_row: Tuple[str, str]) -> str:
    """
    从 PDF 或 DOCX 文件中提取作者元数据。

    Parameters
    ----------
    file_row : (file_name, file_path)
        文件路径元组

    Returns
    -------
    str
        作者名称，提取失败返回 'Unknown Author'
    """
    file_path = file_row[1]
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()

    try:
        if ext == ".pdf":
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                author = reader.metadata.get("/Author", "Unknown Author")
                return str(clean_nul(author))

        elif ext in (".docx", ".doc"):
            doc = Document(file_path)
            author = (
                doc.core_properties.author
                if doc.core_properties.author
                else "Unknown Author"
            )
            return str(clean_nul(author))

        else:
            return "Unsupported File Type"

    except PyPDF2.errors.PdfReadError:
        return "Invalid PDF File"
    except Exception:
        return "Unknown Author"


# ── 主流程 ────────────────────────────────────────────────────────────────


def process_table(table_name: str, sql: str):
    """处理一张表：获取数据 → 提取作者 → 去重 → 写入"""
    logger.info("=" * 50)
    logger.info("开始处理表: %s", table_name)

    # 1. 获取原始数据
    data = get_data(sql)
    if data.empty:
        logger.warning("表 %s 无数据，跳过", table_name)
        return

    # 2. 多进程提取作者
    file_rows: List[Tuple[str, str]] = [
        (row["file_name"], row["file_path"])
        for _, row in data[["file_name", "file_path"]].iterrows()
    ]
    with mp.Pool(processes=min(6, mp.cpu_count())) as pool:
        authors = pool.map(get_author, file_rows)

    data["author"] = [str(a) for a in authors]

    # 3. 去重：排除 Unknown Author
    before = len(data)
    data = data.drop_duplicates(subset=["author"])
    data = data[data["author"] != "Unknown Author"]
    after = len(data)
    logger.info("去重过滤: %d → %d 条", before, after)

    # 4. 写入目标表
    save_data(data, table_name)


def main():
    logger.info("招投标 ETL 脚本启动")

    # 校验文件路径可访问（Linux 路径挂载检查）
    for table_name, sql in BIDDING_SQL.items():
        try:
            process_table(table_name, sql)
        except Exception as e:
            logger.error("处理表 %s 时发生异常: %s", table_name, e, exc_info=True)

    logger.info("全部处理完成")


if __name__ == "__main__":
    main()
