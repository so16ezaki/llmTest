"""
テスト用PDF生成スクリプト
組み込みシステム設計ガイドのサンプルPDFを生成する
"""

from fpdf import FPDF
import os

BASE = os.path.dirname(__file__)

class PDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 8, "Embedded System Design Guide  |  Confidential", align="R")
        self.ln(4)
        self.set_draw_color(180, 180, 180)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")
        self.set_text_color(0)

    def chapter_title(self, title):
        self.set_font("Helvetica", "B", 14)
        self.set_fill_color(230, 240, 255)
        self.cell(0, 10, title, fill=True, ln=True)
        self.ln(3)

    def section_title(self, title):
        self.set_font("Helvetica", "B", 11)
        self.cell(0, 8, title, ln=True)
        self.ln(1)

    def body(self, text):
        self.set_font("Helvetica", "", 10)
        self.multi_cell(0, 6, text)
        self.ln(2)

    def code_block(self, code):
        self.set_font("Courier", "", 9)
        self.set_fill_color(245, 245, 245)
        self.set_draw_color(200, 200, 200)
        self.multi_cell(0, 5, code, border=1, fill=True)
        self.set_draw_color(0, 0, 0)
        self.ln(3)

    def table(self, headers, rows):
        self.set_font("Helvetica", "B", 9)
        col_w = 180 // len(headers)
        self.set_fill_color(200, 220, 255)
        for h in headers:
            self.cell(col_w, 7, h, border=1, fill=True)
        self.ln()
        self.set_font("Helvetica", "", 9)
        for i, row in enumerate(rows):
            fill = (i % 2 == 1)
            self.set_fill_color(248, 248, 248)
            for cell in row:
                self.cell(col_w, 6, str(cell), border=1, fill=fill)
            self.ln()
        self.ln(3)


pdf = PDF()
pdf.set_auto_page_break(auto=True, margin=15)
pdf.add_page()

# ── 表紙 ──────────────────────────────────────────────────────────
pdf.set_font("Helvetica", "B", 24)
pdf.ln(20)
pdf.cell(0, 12, "Embedded System Design Guide", align="C", ln=True)
pdf.set_font("Helvetica", "", 14)
pdf.cell(0, 8, "Sensor Monitoring System", align="C", ln=True)
pdf.ln(4)
pdf.set_font("Helvetica", "I", 10)
pdf.cell(0, 6, "Version 1.2  |  2025-03", align="C", ln=True)
pdf.ln(30)

pdf.set_font("Helvetica", "", 10)
pdf.multi_cell(0, 6,
    "This document describes the architecture, design decisions, and implementation "
    "guidelines for the sensor monitoring subsystem used in embedded control units. "
    "It covers hardware abstraction, interrupt handling, calibration algorithms, and "
    "alert management.\n\n"
    "Target audience: Firmware engineers with C/RTOS experience."
)


# ── Chapter 1 ─────────────────────────────────────────────────────
pdf.add_page()
pdf.chapter_title("Chapter 1: System Architecture")

pdf.section_title("1.1 Overview")
pdf.body(
    "The sensor monitoring system consists of three main components: "
    "the hardware abstraction layer (HAL), the data processing pipeline, "
    "and the alert management module.\n\n"
    "The HAL isolates hardware-specific code (register access, interrupt setup) "
    "from the application logic. This separation allows unit testing without "
    "physical hardware and simplifies board bring-up."
)

pdf.section_title("1.2 Component Diagram")
pdf.body(
    "The following table summarizes the primary modules and their responsibilities:"
)
pdf.table(
    ["Module", "File", "Responsibility"],
    [
        ["Sensor HAL",    "sensor.c", "Read raw ADC values, manage IRQ buffer"],
        ["Logger",        "logger.c", "Leveled log output to stderr/file"],
        ["Main Loop",     "main.c",   "Initialization, polling, shutdown"],
        ["Calibration",   "sensor.c", "Convert raw values to physical units"],
        ["Alert Manager", "sensor.c", "Threshold comparison, level assignment"],
    ]
)

pdf.section_title("1.3 Data Flow")
pdf.body(
    "1. Hardware IRQ fires on new ADC sample.\n"
    "2. sensor_irq_handler() pushes raw byte into circular buffer (g_data_buf).\n"
    "3. Main loop calls process_all_sensors() at POLL_INTERVAL_MS cadence.\n"
    "4. sensor_read() pops from the buffer and applies calibration.\n"
    "5. check_alert() compares calibrated value against per-sensor thresholds.\n"
    "6. If alert fires, log_alert() formats and emits the log entry."
)


# ── Chapter 2 ─────────────────────────────────────────────────────
pdf.add_page()
pdf.chapter_title("Chapter 2: Interrupt Handling and Concurrency")

pdf.section_title("2.1 Circular Buffer")
pdf.body(
    "The IRQ handler and main loop share a circular byte buffer. "
    "The buffer head pointer (g_buf_head) is written only by the IRQ handler; "
    "the tail pointer (g_buf_tail) is read/written only by the main loop.\n\n"
    "IMPORTANT: On single-core MCUs without preemption between ISR and main, "
    "this one-producer/one-consumer pattern is safe without a mutex. "
    "However, on multi-core or preemptible RTOS environments, "
    "atomic operations or a spinlock MUST be used."
)

pdf.section_title("2.2 Volatile Qualifier")
pdf.body(
    "All shared variables are declared volatile to prevent the compiler from "
    "caching them in registers:\n"
    "  - g_data_buf[DATA_BUF_SIZE]\n"
    "  - g_buf_head, g_buf_tail\n"
    "  - g_irq_fired\n\n"
    "Without volatile, optimizing compilers may hoist reads out of loops, "
    "causing the main loop to never observe IRQ updates."
)

pdf.section_title("2.3 Known Limitations")
pdf.body(
    "The current implementation has the following known limitations:\n\n"
    "- Buffer overflow is silently dropped (new sample discarded when full).\n"
    "- No timestamp is attached to samples (RTC not yet integrated).\n"
    "- Only single-byte samples are supported; multi-byte sensors need framing.\n"
    "- The IRQ handler does not debounce or validate the ADC reading."
)


# ── Chapter 3 ─────────────────────────────────────────────────────
pdf.add_page()
pdf.chapter_title("Chapter 3: Calibration Algorithm")

pdf.section_title("3.1 Linear Calibration Model")
pdf.body(
    "Each sensor uses a linear calibration model:\n\n"
    "    calibrated = raw * scale + offset\n\n"
    "The coefficients are stored in static arrays s_calib_scale[] and "
    "s_calib_offset[], indexed by sensor ID. "
    "They are set during sensor_init() based on sensor type."
)

pdf.section_title("3.2 Per-Sensor Coefficients")
pdf.table(
    ["Sensor ID", "Type", "Scale", "Offset", "Unit"],
    [
        ["0 (TEMP)",   "Temperature",  "0.01",  "-40.0", "degC"],
        ["1 (HUMID)",  "Humidity",     "0.1",   "0.0",   "% RH"],
        ["2 (PRESS)",  "Pressure",     "0.01",  "800.0", "hPa"],
    ]
)

pdf.section_title("3.3 Calibration Update Procedure")
pdf.body(
    "To update calibration coefficients in the field:\n\n"
    "1. Place sensor in a known reference environment.\n"
    "2. Read 100 samples and compute the mean raw value.\n"
    "3. Solve for offset: offset = reference - mean_raw * scale.\n"
    "4. Write new offset to non-volatile storage.\n"
    "5. Call sensor_init() to reload coefficients on next boot.\n\n"
    "Note: scale coefficient is assumed stable and not field-adjustable "
    "in the current firmware version."
)


# ── Chapter 4 ─────────────────────────────────────────────────────
pdf.add_page()
pdf.chapter_title("Chapter 4: Alert Management")

pdf.section_title("4.1 Alert Levels")
pdf.body(
    "The system defines three alert levels:"
)
pdf.table(
    ["Level", "Value", "Meaning", "Log Destination"],
    [
        ["ALERT_NONE",     "0", "No issue detected",         "-"],
        ["ALERT_WARNING",  "1", "Threshold exceeded",        "LOG_WARN"],
        ["ALERT_CRITICAL", "2", "Threshold x1.5 exceeded",   "LOG_ERROR"],
    ]
)

pdf.section_title("4.2 Temperature Alert Thresholds")
pdf.body(
    "Temperature alerts use a symmetric threshold relative to a configured limit T:\n\n"
    "  CRITICAL : calibrated > T * 1.5  OR  calibrated < -T * 1.5\n"
    "  WARNING  : calibrated > T        OR  calibrated < -T\n\n"
    "Default threshold T for temperature sensor: 85.0 degC"
)

pdf.section_title("4.3 Humidity and Pressure Alerts")
pdf.body(
    "Humidity:\n"
    "  WARNING  : calibrated > 90.0 %RH\n"
    "  CRITICAL : calibrated > 95.0 %RH  (note: implementation bug - see errata)\n\n"
    "Pressure:\n"
    "  WARNING  : calibrated < 900.0 hPa  OR  calibrated > 1100.0 hPa"
)

pdf.section_title("4.4 Errata: Humidity CRITICAL Unreachable")
pdf.body(
    "BUG (tracked as ISSUE-42): In check_alert(), the ALERT_CRITICAL branch for "
    "humidity (>95.0) is unreachable because the preceding WARNING branch (>90.0) "
    "returns first. The condition ordering must be reversed:\n\n"
    "  Correct order:\n"
    "    if (calibrated > 95.0) return ALERT_CRITICAL;\n"
    "    if (calibrated > 90.0) return ALERT_WARNING;"
)


# ── Chapter 5 ─────────────────────────────────────────────────────
pdf.add_page()
pdf.chapter_title("Chapter 5: Coding Guidelines and Known Issues")

pdf.section_title("5.1 Buffer Safety")
pdf.body(
    "All string formatting operations MUST use snprintf() with explicit size limits. "
    "The current log_alert() implementation uses sprintf() without bounds checking "
    "(BUG: ISSUE-43). This must be fixed before production release:\n"
)
pdf.code_block(
    "/* WRONG - no bounds check */\n"
    "sprintf(msg, \"[ALERT] level=%d sensor=%d ...\", ...);\n\n"
    "/* CORRECT */\n"
    "snprintf(msg, sizeof(msg), \"[ALERT] level=%d sensor=%d ...\", ...);"
)

pdf.section_title("5.2 Uninitialized Variable Warning")
pdf.body(
    "sensor_read() declares 'int16_t raw;' without initialization. "
    "On builds where the hardware register read macro is not defined, "
    "raw retains an indeterminate value. "
    "Always initialize local variables at declaration (C99 allows this):\n"
)
pdf.code_block("int16_t raw = 0;  /* safe default until hardware read succeeds */")

pdf.section_title("5.3 Unused Code")
pdf.body(
    "_sensor_selftest() is defined but never called. "
    "Dead code increases binary size and confuses code reviewers. "
    "Either integrate it into the CI test suite or remove it."
)

pdf.section_title("5.4 Build Requirements")
pdf.table(
    ["Item", "Requirement"],
    [
        ["Compiler",    "GCC 10+ or Clang 12+"],
        ["C Standard",  "C99 minimum, C11 preferred"],
        ["Warnings",    "-Wall -Wextra -Werror recommended"],
        ["Optimization","-O2 for release, -O0 -g for debug"],
        ["RTOS",        "FreeRTOS 10.x (optional, single-threaded mode supported)"],
    ]
)


# ── 保存 ─────────────────────────────────────────────────────────
out_path = os.path.join(BASE, "embedded_design_guide.pdf")
pdf.output(out_path)
print(f"Generated: {out_path}")
