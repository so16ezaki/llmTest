"""
LDF Editor - LIN 2.0 Description File Editor
==============================================
LDFファイルをパースし、ノード・フレーム・シグナルを
pandas DataFrameとして操作できるライブラリ。

Usage:
    editor = LdfEditor("sample.ldf")
    # DataFrameで確認
    print(editor.nodes_df)
    print(editor.frames_df)
    print(editor.signals_df)
    # 編集してから保存
    editor.save("output.ldf")
"""

import re
import copy
import pandas as pd
from pathlib import Path
from typing import Optional


class LdfEditor:
    """LIN 2.0 LDFファイルの読み込み・編集・保存を行うクラス。"""

    def __init__(self, filepath: str):
        self._filepath = Path(filepath)
        self._raw_text = self._filepath.read_text(encoding="utf-8")

        # パース結果の内部データ
        self._nodes: list[dict] = []
        self._frames: list[dict] = []
        self._signals: list[dict] = []
        self._schedule_tables: dict[str, list[dict]] = {}  # {table_name: [{frame, delay}, ...]}

        # セクション別の生テキスト（フォーマット保持用）
        self._sections: dict[str, str] = {}
        # セクション以外の部分（ヘッダ、コメント等）を順序付きで保持
        self._structure: list[dict] = []

        self._parse()

    # ──────────────────────────────────────────────
    # DataFrame プロパティ
    # ──────────────────────────────────────────────

    @property
    def nodes_df(self) -> pd.DataFrame:
        """ノード一覧をDataFrameで返す。
        columns: name, role(Master/Slave), time_base, jitter
        """
        return pd.DataFrame(self._nodes)

    @nodes_df.setter
    def nodes_df(self, df: pd.DataFrame):
        self._nodes = df.to_dict(orient="records")

    @property
    def frames_df(self) -> pd.DataFrame:
        """フレーム一覧をDataFrameで返す。
        columns: name, frame_id, publisher, size
        """
        return pd.DataFrame(self._frames)

    @frames_df.setter
    def frames_df(self, df: pd.DataFrame):
        self._frames = df.to_dict(orient="records")

    @property
    def signals_df(self) -> pd.DataFrame:
        """シグナル一覧をDataFrameで返す。
        columns: name, size, init_value, publisher, subscribers, frame, offset
        """
        return pd.DataFrame(self._signals)

    @signals_df.setter
    def signals_df(self, df: pd.DataFrame):
        self._signals = df.to_dict(orient="records")

    @property
    def schedule_tables_df(self) -> pd.DataFrame:
        """スケジュールテーブル一覧をDataFrameで返す。
        columns: table, frame, delay_ms
        """
        rows = []
        for table_name, entries in self._schedule_tables.items():
            for entry in entries:
                rows.append({
                    "table": table_name,
                    "frame": entry["frame"],
                    "delay_ms": entry["delay_ms"],
                })
        return pd.DataFrame(rows)

    @schedule_tables_df.setter
    def schedule_tables_df(self, df: pd.DataFrame):
        self._schedule_tables = {}
        for _, row in df.iterrows():
            table = row["table"]
            if table not in self._schedule_tables:
                self._schedule_tables[table] = []
            self._schedule_tables[table].append({
                "frame": row["frame"],
                "delay_ms": row["delay_ms"],
            })

    # ──────────────────────────────────────────────
    # 便利メソッド（DataFrameを直接触らなくても使える）
    # ──────────────────────────────────────────────

    def add_node(self, name: str, role: str = "Slave",
                 time_base: float = 0.0, jitter: float = 0.0):
        """ノードを追加する。"""
        self._nodes.append({
            "name": name,
            "role": role,
            "time_base": time_base,
            "jitter": jitter,
        })

    def add_frame(self, name: str, frame_id: int,
                  publisher: str, size: int):
        """フレームを追加する。"""
        self._frames.append({
            "name": name,
            "frame_id": frame_id,
            "publisher": publisher,
            "size": size,
        })

    def _next_start_bit(self, frame_name: str) -> int:
        """指定フレーム内で次に使えるstart bitを返す。"""
        frame_sigs = [s for s in self._signals if s["frame"] == frame_name]
        if not frame_sigs:
            return 0
        return max(s["offset"] + s["size"] for s in frame_sigs)

    def add_signal(self, name: str, size: int, init_value=0,
                   publisher: str = "", subscribers: str = "",
                   frame: str = "", offset: Optional[int] = None):
        """シグナルを追加する。offset=Noneならstart bitを自動計算。"""
        if offset is None and frame:
            offset = self._next_start_bit(frame)
        elif offset is None:
            offset = 0
        self._signals.append({
            "name": name,
            "size": size,
            "init_value": init_value,
            "publisher": publisher,
            "subscribers": subscribers,
            "frame": frame,
            "offset": offset,
        })

    def add_signals_auto(self, entries: list):
        """シグナルを一括登録し、start bitを自動計算する。

        タプル/リストで簡潔に入力可能:
            editor.add_signals_auto([
                ("MotorStatus", "Sig1", 8),
                ("MotorStatus", "Sig2", 4),
                ("SensorData",  "Sig3", 16),
            ])
        順序: (frame, signal_name, size)
        追加項目も指定可: (frame, signal_name, size, init_value, publisher, subscribers)

        dict形式・DataFrame.to_dict(orient='records')も引き続き使用可。
        """
        for entry in entries:
            if isinstance(entry, (tuple, list)):
                frame = entry[0]
                name = entry[1]
                size = int(entry[2])
                init_value = entry[3] if len(entry) > 3 else 0
                publisher = entry[4] if len(entry) > 4 else ""
                subscribers = entry[5] if len(entry) > 5 else ""
            else:
                frame = entry.get("frame", "")
                name = entry.get("name", entry.get("signal_name", ""))
                size = int(entry.get("size", entry.get("signal_size", 0)))
                init_value = entry.get("init_value", 0)
                publisher = entry.get("publisher", entry.get("signal_publisher", ""))
                subscribers = entry.get("subscribers", "")
            self.add_signal(
                name=name,
                size=size,
                init_value=init_value,
                publisher=publisher,
                subscribers=subscribers,
                frame=frame,
                offset=None,
            )

    def add_signals_auto_df(self, df: pd.DataFrame):
        """DataFrameからシグナルを一括登録（start bit自動計算）。
        最低限のcolumns: frame, name, size
        省略可: publisher, subscribers, init_value

        Example:
            df = pd.DataFrame([
                {"frame": "MotorStatus", "name": "Sig1", "size": 8},
                {"frame": "MotorStatus", "name": "Sig2", "size": 4},
            ])
            editor.add_signals_auto_df(df)
        """
        self.add_signals_auto(df.to_dict(orient="records"))

    def add_frames_bulk(self, df: pd.DataFrame):
        """DataFrameからフレームを一括登録する。
        columns: name, frame_id, publisher, size
        """
        for _, row in df.iterrows():
            self._frames.append(row.to_dict())

    def add_signals_bulk(self, df: pd.DataFrame):
        """DataFrameからシグナルを一括登録する。
        columns: name, size, init_value, publisher, subscribers, frame, offset
        """
        for _, row in df.iterrows():
            rec = row.to_dict()
            rec.setdefault("frame", "")
            rec.setdefault("offset", 0)
            self._signals.append(rec)

    def add_frames_and_signals_bulk(self, df: pd.DataFrame):
        """フレームとシグナルをまとめて一括登録する。
        columns: frame_name, frame_id, publisher, frame_size,
                 signal_name, signal_size, init_value, signal_publisher,
                 subscribers, offset

        同じframe_nameの行はフレームを1つにまとめ、シグナルを複数登録する。
        """
        registered_frames = set(f["name"] for f in self._frames)
        for _, row in df.iterrows():
            fname = row["frame_name"]
            if fname not in registered_frames:
                self._frames.append({
                    "name": fname,
                    "frame_id": row["frame_id"],
                    "publisher": row["publisher"],
                    "size": row["frame_size"],
                })
                registered_frames.add(fname)
            self._signals.append({
                "name": row["signal_name"],
                "size": row["signal_size"],
                "init_value": row.get("init_value", 0),
                "publisher": row.get("signal_publisher", row["publisher"]),
                "subscribers": row.get("subscribers", ""),
                "frame": fname,
                "offset": row.get("offset", 0),
            })

    def edit_node(self, name: str, **kwargs):
        """既存ノードの属性を変更する。"""
        for node in self._nodes:
            if node["name"] == name:
                node.update(kwargs)
                return
        raise KeyError(f"Node '{name}' not found")

    def edit_frame(self, name: str, **kwargs):
        """既存フレームの属性を変更する。"""
        for frame in self._frames:
            if frame["name"] == name:
                frame.update(kwargs)
                return
        raise KeyError(f"Frame '{name}' not found")

    def edit_signal(self, name: str, **kwargs):
        """既存シグナルの属性を変更する。"""
        for sig in self._signals:
            if sig["name"] == name:
                sig.update(kwargs)
                return
        raise KeyError(f"Signal '{name}' not found")

    def delete_node(self, name: str, cascade: bool = False):
        """ノードを削除する。
        cascade=True の場合、そのノードがpublisherのフレーム・シグナルも削除。
        """
        orig_len = len(self._nodes)
        self._nodes = [n for n in self._nodes if n["name"] != name]
        if len(self._nodes) == orig_len:
            raise KeyError(f"Node '{name}' not found")
        if cascade:
            del_frames = [f["name"] for f in self._frames if f["publisher"] == name]
            self._frames = [f for f in self._frames if f["publisher"] != name]
            self._signals = [
                s for s in self._signals
                if s["publisher"] != name and s["frame"] not in del_frames
            ]

    def delete_frame(self, name: str, cascade: bool = False):
        """フレームを削除する。
        cascade=True の場合、フレームに紐づくシグナルのframe/offsetもクリア。
        """
        orig_len = len(self._frames)
        self._frames = [f for f in self._frames if f["name"] != name]
        if len(self._frames) == orig_len:
            raise KeyError(f"Frame '{name}' not found")
        if cascade:
            for sig in self._signals:
                if sig["frame"] == name:
                    sig["frame"] = ""
                    sig["offset"] = 0

    def delete_signal(self, name: str):
        """シグナルを削除する。"""
        orig_len = len(self._signals)
        self._signals = [s for s in self._signals if s["name"] != name]
        if len(self._signals) == orig_len:
            raise KeyError(f"Signal '{name}' not found")

    def add_schedule_table(self, table_name: str, entries: list):
        """スケジュールテーブルを追加する。
        タプル形式: [(frame, delay_ms), ...]
            editor.add_schedule_table("MainSchedule", [
                ("MotorStatus", 10),
                ("SensorData",  10),
                ("MotorCmd",    10),
            ])
        dict形式も可: [{"frame": "MotorStatus", "delay_ms": 10}, ...]
        """
        parsed = []
        for entry in entries:
            if isinstance(entry, (tuple, list)):
                parsed.append({"frame": entry[0], "delay_ms": entry[1]})
            else:
                parsed.append(entry)
        self._schedule_tables[table_name] = parsed

    def add_schedule_entry(self, table_name: str, frame: str, delay_ms: float):
        """既存テーブルにエントリを追加する。"""
        if table_name not in self._schedule_tables:
            self._schedule_tables[table_name] = []
        self._schedule_tables[table_name].append({
            "frame": frame,
            "delay_ms": delay_ms,
        })

    def delete_schedule_table(self, table_name: str):
        """スケジュールテーブルを削除する。"""
        if table_name not in self._schedule_tables:
            raise KeyError(f"Schedule table '{table_name}' not found")
        del self._schedule_tables[table_name]

    def delete_schedule_entry(self, table_name: str, frame: str):
        """テーブル内の指定フレームのエントリを削除する。"""
        if table_name not in self._schedule_tables:
            raise KeyError(f"Schedule table '{table_name}' not found")
        orig_len = len(self._schedule_tables[table_name])
        self._schedule_tables[table_name] = [
            e for e in self._schedule_tables[table_name] if e["frame"] != frame
        ]
        if len(self._schedule_tables[table_name]) == orig_len:
            raise KeyError(f"Entry '{frame}' not found in '{table_name}'")

    # ──────────────────────────────────────────────
    # パーサー
    # ──────────────────────────────────────────────

    def _parse(self):
        text = self._raw_text
        self._parse_structure(text)
        self._parse_nodes(self._sections.get("Nodes", ""))
        self._parse_signals_section(self._sections.get("Signals", ""))
        self._parse_frames_section(self._sections.get("Frames", ""))
        self._parse_schedule_tables(self._sections.get("Schedule_tables", ""))

    def _parse_structure(self, text: str):
        """セクション境界を検出し、構造を保持する。"""
        # セクション名の候補
        section_names = [
            "LIN_description_file", "LIN_protocol_version",
            "LIN_language_version", "LIN_speed",
            "Nodes", "Signals", "Frames",
            "Diagnostic_signals", "Diagnostic_frames",
            "Signal_groups", "Signal_encoding_types",
            "Signal_representation", "Schedule_tables",
            "Node_attributes",
        ]

        # ブレース付きセクションを抽出
        brace_pattern = re.compile(
            r'^(\s*((?:' + '|'.join(section_names) + r'))\s*\{)',
            re.MULTILINE
        )

        pos = 0
        for m in brace_pattern.finditer(text):
            # セクション開始前のテキスト
            if m.start() > pos:
                self._structure.append({
                    "type": "raw",
                    "content": text[pos:m.start()]
                })

            section_name = m.group(2).strip()
            # 対応する閉じブレースを探す
            brace_start = m.start()
            depth = 0
            brace_end = brace_start
            for i in range(m.end() - 1, len(text)):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        brace_end = i + 1
                        break

            section_text = text[brace_start:brace_end]
            self._sections[section_name] = section_text
            self._structure.append({
                "type": "section",
                "name": section_name,
                "original": section_text,
            })
            pos = brace_end

        # 残りのテキスト
        if pos < len(text):
            remaining = text[pos:]
            # ヘッダ行（LIN_description_file ; 等）も残り部分に含まれうる
            self._structure.append({"type": "raw", "content": remaining})

        # ブレースなしのヘッダ行を個別にパース
        header_patterns = {
            "LIN_protocol_version": r'LIN_protocol_version\s*=\s*"([^"]+)"\s*;',
            "LIN_language_version": r'LIN_language_version\s*=\s*"([^"]+)"\s*;',
            "LIN_speed": r'LIN_speed\s*=\s*([\d.]+)\s*kbps\s*;',
        }
        for key, pat in header_patterns.items():
            m = re.search(pat, text)
            if m:
                self._sections[key] = m.group(0)

    def _parse_nodes(self, section: str):
        if not section:
            return
        # Master: name, time_base, jitter ;
        master_m = re.search(
            r'Master\s*:\s*(\w+)\s*,\s*([\d.]+)\s*ms\s*,\s*([\d.]+)\s*ms\s*;',
            section
        )
        if master_m:
            self._nodes.append({
                "name": master_m.group(1),
                "role": "Master",
                "time_base": float(master_m.group(2)),
                "jitter": float(master_m.group(3)),
            })

        # Slaves: name1, name2, ... ;
        slaves_m = re.search(r'Slaves\s*:\s*([^;]+);', section)
        if slaves_m:
            names = [n.strip() for n in slaves_m.group(1).split(',') if n.strip()]
            for name in names:
                self._nodes.append({
                    "name": name,
                    "role": "Slave",
                    "time_base": 0.0,
                    "jitter": 0.0,
                })

    def _parse_signals_section(self, section: str):
        if not section:
            return
        # signal_name: size, init_value, publisher, subscriber1, subscriber2, ... ;
        pat = re.compile(
            r'(\w+)\s*:\s*(\d+)\s*,\s*(\{[^}]*\}|[\w.]+)\s*,\s*(\w+)\s*,\s*([^;]+);'
        )
        for m in pat.finditer(section):
            subscribers = ', '.join(s.strip() for s in m.group(5).split(',') if s.strip())
            self._signals.append({
                "name": m.group(1),
                "size": int(m.group(2)),
                "init_value": m.group(3).strip(),
                "publisher": m.group(4).strip(),
                "subscribers": subscribers,
                "frame": "",
                "offset": 0,
            })

    def _parse_frames_section(self, section: str):
        if not section:
            return
        # Frame_name: frame_id, publisher, size { signal_name, offset; ... }
        frame_pat = re.compile(
            r'(\w+)\s*:\s*(0x[0-9A-Fa-f]+|\d+)\s*,\s*(\w+)\s*,\s*(\d+)\s*\{([^}]*)\}'
        )
        for m in frame_pat.finditer(section):
            frame_name = m.group(1)
            fid_str = m.group(2)
            frame_id = int(fid_str, 16) if fid_str.startswith("0x") else int(fid_str)
            publisher = m.group(3)
            size = int(m.group(4))

            self._frames.append({
                "name": frame_name,
                "frame_id": frame_id,
                "publisher": publisher,
                "size": size,
            })

            # フレーム内のシグナルマッピング
            sig_pat = re.compile(r'(\w+)\s*,\s*(\d+)\s*;')
            for sm in sig_pat.finditer(m.group(5)):
                sig_name = sm.group(1)
                offset = int(sm.group(2))
                for sig in self._signals:
                    if sig["name"] == sig_name:
                        sig["frame"] = frame_name
                        sig["offset"] = offset

    def _parse_schedule_tables(self, section: str):
        if not section:
            return
        # Schedule_tables { TableName { frame delay ms; ... } ... }
        table_pat = re.compile(r'(\w+)\s*\{([^}]*)\}')
        # 外側のブレースの中身を取得
        inner_m = re.search(r'Schedule_tables\s*\{(.+)\}', section, re.DOTALL)
        if not inner_m:
            return
        inner = inner_m.group(1)
        for tm in table_pat.finditer(inner):
            table_name = tm.group(1)
            entries_text = tm.group(2)
            entries = []
            entry_pat = re.compile(r'(\w+)\s+delay\s+([\d.]+)\s*ms\s*;')
            for em in entry_pat.finditer(entries_text):
                entries.append({
                    "frame": em.group(1),
                    "delay_ms": float(em.group(2)),
                })
            self._schedule_tables[table_name] = entries

    # ──────────────────────────────────────────────
    # 保存（フォーマット維持 + 変更反映）
    # ──────────────────────────────────────────────

    def save(self, filepath: Optional[str] = None):
        """編集内容をLDFファイルとして保存する。"""
        out_path = Path(filepath) if filepath else self._filepath
        output = self._rebuild()
        out_path.write_text(output, encoding="utf-8")

    def _rebuild(self) -> str:
        """内部データから全体テキストを再構築する。"""
        parts = []
        for item in self._structure:
            if item["type"] == "raw":
                parts.append(item["content"])
            elif item["type"] == "section":
                name = item["name"]
                if name == "Nodes":
                    parts.append(self._rebuild_nodes(item["original"]))
                elif name == "Signals":
                    parts.append(self._rebuild_signals(item["original"]))
                elif name == "Frames":
                    parts.append(self._rebuild_frames(item["original"]))
                elif name == "Schedule_tables":
                    parts.append(self._rebuild_schedule_tables(item["original"]))
                else:
                    # 未対応セクションはそのまま維持
                    parts.append(item["original"])
        result = ''.join(parts)
        # 新規追加されたSchedule_tablesセクション（元LDFに無かった場合）
        has_schedule = any(
            item.get("name") == "Schedule_tables"
            for item in self._structure if item["type"] == "section"
        )
        if self._schedule_tables and not has_schedule:
            result = result.rstrip('\n') + '\n\n' + self._rebuild_schedule_tables("") + '\n'
        return result

    def _rebuild_nodes(self, original: str) -> str:
        """Nodesセクションを再構築する。"""
        master = [n for n in self._nodes if n["role"] == "Master"]
        slaves = [n for n in self._nodes if n["role"] == "Slave"]

        # インデントを元テキストから推定
        indent = self._detect_indent(original)

        lines = ["Nodes {"]
        if master:
            m = master[0]
            lines.append(
                f'{indent}Master: {m["name"]}, '
                f'{m["time_base"]:.1f} ms, {m["jitter"]:.1f} ms ;'
            )
        if slaves:
            slave_names = ", ".join(s["name"] for s in slaves)
            lines.append(f'{indent}Slaves: {slave_names} ;')
        lines.append("}")
        return '\n'.join(lines) + '\n'

    def _rebuild_signals(self, original: str) -> str:
        """Signalsセクションを再構築する。"""
        indent = self._detect_indent(original)
        lines = ["Signals {"]
        for sig in self._signals:
            lines.append(
                f'{indent}{sig["name"]}: {sig["size"]}, {sig["init_value"]}, '
                f'{sig["publisher"]}, {sig["subscribers"]} ;'
            )
        lines.append("}")
        return '\n'.join(lines) + '\n'

    def _rebuild_frames(self, original: str) -> str:
        """Framesセクションを再構築する。"""
        indent = self._detect_indent(original)
        indent2 = indent * 2

        lines = ["Frames {"]
        for frame in self._frames:
            fid = f'0x{frame["frame_id"]:02X}'
            lines.append(
                f'{indent}{frame["name"]}: {fid}, '
                f'{frame["publisher"]}, {frame["size"]} {{'
            )
            # このフレームに属するシグナル
            frame_sigs = [s for s in self._signals if s["frame"] == frame["name"]]
            frame_sigs.sort(key=lambda s: s["offset"])
            for sig in frame_sigs:
                lines.append(f'{indent2}{sig["name"]}, {sig["offset"]} ;')
            lines.append(f'{indent}}}')
        lines.append("}")
        return '\n'.join(lines) + '\n'

    def _rebuild_schedule_tables(self, original: str) -> str:
        """Schedule_tablesセクションを再構築する。"""
        indent = self._detect_indent(original) if original else "  "
        indent2 = indent * 2

        lines = ["Schedule_tables {"]
        for table_name, entries in self._schedule_tables.items():
            lines.append(f'{indent}{table_name} {{')
            for entry in entries:
                lines.append(
                    f'{indent2}{entry["frame"]} delay {entry["delay_ms"]:.1f} ms ;'
                )
            lines.append(f'{indent}}}')
        lines.append("}")
        return '\n'.join(lines) + '\n'

    @staticmethod
    def _detect_indent(text: str) -> str:
        """テキストからインデント文字を推定する。"""
        for line in text.split('\n'):
            stripped = line.lstrip()
            if stripped and line != stripped:
                return line[:len(line) - len(stripped)]
        return "  "

    # ──────────────────────────────────────────────
    # バリデーション
    # ──────────────────────────────────────────────

    def validate(self) -> list[str]:
        """基本的な整合性チェックを行い、警告メッセージのリストを返す。"""
        warnings = []
        node_names = {n["name"] for n in self._nodes}
        frame_names = {f["name"] for f in self._frames}

        for sig in self._signals:
            if sig["publisher"] and sig["publisher"] not in node_names:
                warnings.append(
                    f'Signal "{sig["name"]}": publisher "{sig["publisher"]}" '
                    f'is not in Nodes'
                )
            if sig["frame"] and sig["frame"] not in frame_names:
                warnings.append(
                    f'Signal "{sig["name"]}": frame "{sig["frame"]}" '
                    f'is not in Frames'
                )

        for frame in self._frames:
            if frame["publisher"] not in node_names:
                warnings.append(
                    f'Frame "{frame["name"]}": publisher "{frame["publisher"]}" '
                    f'is not in Nodes'
                )
            # フレームサイズチェック
            frame_sigs = [s for s in self._signals if s["frame"] == frame["name"]]
            for sig in frame_sigs:
                end_bit = sig["offset"] + sig["size"]
                if end_bit > frame["size"] * 8:
                    warnings.append(
                        f'Signal "{sig["name"]}" exceeds frame '
                        f'"{frame["name"]}" size ({end_bit} > {frame["size"] * 8} bits)'
                    )

        return warnings


# ──────────────────────────────────────────────
# 使用例
# ──────────────────────────────────────────────

if __name__ == "__main__":
    # ============================================================
    # 設定（ここを編集する）
    # ============================================================

    INPUT_FILE = "sample.ldf"
    OUTPUT_FILE = "output.ldf"

    # --- ノード追加 ---
    NEW_NODES = [
        # (name, role)
        # ("Sensor2", "Slave"),
    ]

    # --- フレーム追加 ---
    NEW_FRAMES = [
        # (name, frame_id, publisher, size)
        # ("LightStatus", 0x10, "Motor1", 2),
    ]

    # --- シグナル追加（start bit自動計算） ---
    NEW_SIGNALS = [
        # (frame, signal_name, size)
        # (frame, signal_name, size, init_value, publisher, subscribers)
        # ("MotorStatus", "MotorError", 4),
        # ("MotorStatus", "MotorMode",  4),
    ]

    # --- シグナル編集 ---
    SIGNAL_EDITS = {
        # "signal_name": {"属性": 値},
        # "MotorSpeed": {"init_value": "0xFF"},
    }

    # --- フレーム編集 ---
    FRAME_EDITS = {
        # "frame_name": {"属性": 値},
        # "MotorStatus": {"size": 8},
    }

    # --- ノード編集 ---
    NODE_EDITS = {
        # "node_name": {"属性": 値},
        # "ECU_Master": {"time_base": 10.0},
    }

    # --- 削除 ---
    DELETE_NODES = [
        # ("node_name", cascade=True/False),
    ]
    DELETE_FRAMES = [
        # ("frame_name", cascade=True/False),
    ]
    DELETE_SIGNALS = [
        # "signal_name",
    ]

    # --- スケジュールテーブル追加 ---
    NEW_SCHEDULE_TABLES = {
        # "TableName": [(frame, delay_ms), ...],
        # "MainSchedule": [
        #     ("MotorStatus", 10),
        #     ("SensorData",  10),
        #     ("MotorCmd",    10),
        # ],
    }

    # ============================================================
    # 実行（以下は編集不要）
    # ============================================================

    editor = LdfEditor(INPUT_FILE)

    for name, role in NEW_NODES:
        editor.add_node(name, role)

    for name, fid, pub, size in NEW_FRAMES:
        editor.add_frame(name, fid, pub, size)

    editor.add_signals_auto(NEW_SIGNALS)

    for name, attrs in SIGNAL_EDITS.items():
        editor.edit_signal(name, **attrs)

    for name, attrs in FRAME_EDITS.items():
        editor.edit_frame(name, **attrs)

    for name, attrs in NODE_EDITS.items():
        editor.edit_node(name, **attrs)

    for item in DELETE_SIGNALS:
        editor.delete_signal(item)

    for name, cascade in DELETE_FRAMES:
        editor.delete_frame(name, cascade=cascade)

    for name, cascade in DELETE_NODES:
        editor.delete_node(name, cascade=cascade)

    for table_name, entries in NEW_SCHEDULE_TABLES.items():
        editor.add_schedule_table(table_name, entries)

    # 結果表示
    print("=== Nodes ===")
    print(editor.nodes_df.to_string(index=False))
    print("\n=== Frames ===")
    print(editor.frames_df.to_string(index=False))
    print("\n=== Signals ===")
    print(editor.signals_df.to_string(index=False))
    st_df = editor.schedule_tables_df
    if not st_df.empty:
        print("\n=== Schedule Tables ===")
        print(st_df.to_string(index=False))

    warnings = editor.validate()
    if warnings:
        print("\n=== Warnings ===")
        for w in warnings:
            print(f"  - {w}")

    editor.save(OUTPUT_FILE)
    print(f"\nSaved to {OUTPUT_FILE}")