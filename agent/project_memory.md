# Project Memory

このファイルはセッションを跨いで保持すべき情報を記録します（CLAUDE.md相当）。
エージェントが `memory_write` ツールで書き込み、セッション開始時に先頭25KBがロードされます。

---

## [project_info]

- プロジェクト名: Dify ナレッジエージェント
- 作成日: 2026-04-03
- 設計原則: "The agent is the model. The code is the harness."
- LLM: Dify Cloud API（モデルはconfig.pyで設定）

---

## [architecture_decisions]

- エージェントループ: while(tool_call) 単一ループ（マルチエージェント不使用）
- ツール結果リマインダー: TOOL_REMINDERS辞書でツール別に固定テキストを付与
- スキルロード: セッション開始時はindex.mdの概要のみ、本文はread_skill時にオンデマンドロード
- コンパクション: 3層（Tier1: ツール結果クリア / Tier2: ローカル圧縮 / Tier3: LLM要約）

---

## [open_questions]

- Difyのfunction calling対応可否（未確認）
- budget_usd制限の導入要否
- keyword_searchの事前インデックス要否（スキル数次第）

---

<!-- エージェントはここに新しい情報を memory_write ツールで追記します -->

## project_summary
### プロジェクト概要: c_project

**ファイル構成**
- `include/` (2 ファイル)
  - `logger.h` (663B)
  - `sensor.h` (1,294B)
- `src/` (3 ファイル)
  - `logger.c` (751B)
  - `main.c` (2,516B)
  - `sensor.c` (6,246B)
- `Makefile` (300B)

**呼び出し関係の主な流れ**
- `init_system` がプロジェクトの初期化を担当し、`logger_init` および `sensor_init` を呼び出す。
- `run_monitor` がセンサシステムを監視し、`process_all_sensors` を実行。
- `sensor.c` 内の `sensor_read` が `sensor_calibrate` と `_sensor_selftest` を経由して処理を行う。

**発見**
- `log_alert` が `sprintf` を利用しているため、バッファオーバーフローのリスクが生じている可能性がある。
- `process_all_sensors` が複数回呼び出されるため、コードの複雑度が高く、保守が難しい可能性がある。

**次に調査すべき項目**
1. `log_alert` における `sprintf` のバッファサイズが適切かを確認 (static_analysis(analysis='issues'))
2. `process_all_sensors` の複雑度を解析 (static_analysis(analysis='complexity'))
3. モジュール間の依存関係を確認 (static_analysis(analysis='dependency_graph'))

## project_dependencies
C_projectディレクトリ内ではsensor_irq_handlerとloggerの2つの主要モジュールが依存関係を持ち、loggerはスレッドセーフ性の検証が必要。ライフサイクル図作成にあたり、dependecy_map.jsonの生成が最優先。

## project_path
C:/Users/so16e/Documents/vscode/python/llmtest/llmTest/test_data/c_project

## lifecycle_sequence
init_system → logger_init → sensor_init → run_monitor → process_all_sensors → sensor_read → sensor_calibrate → _sensor_selftest
