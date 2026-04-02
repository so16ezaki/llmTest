/*
 * sensor.c — センサーデータ取得・処理実装
 *
 * 注意: このファイルにはテスト用に意図的な問題を含む
 *   - グローバル変数への非排他アクセス（IRQ競合）
 *   - 未初期化変数の使用（sensor_read内）
 *   - バッファオーバーフローの可能性（log_alert内）
 *   - 未使用関数（_sensor_selftest）
 */

#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include "sensor.h"
#include "logger.h"

/* グローバル変数定義 */
volatile uint8_t  g_data_buf[DATA_BUF_SIZE];
volatile uint16_t g_buf_head = 0;
volatile uint16_t g_buf_tail = 0;
volatile bool     g_irq_fired = false;

/* キャリブレーション係数（センサーID別） */
static float s_calib_offset[SENSOR_MAX] = {0.0f, 0.0f, 0.0f};
static float s_calib_scale[SENSOR_MAX]  = {1.0f, 1.0f, 1.0f};

/* 初期化フラグ */
static bool s_initialized[SENSOR_MAX] = {false, false, false};


/*
 * sensor_init — センサーの初期化
 */
int sensor_init(uint8_t id)
{
    if (id >= SENSOR_MAX) {
        LOG_E("sensor_init: invalid id=%d", id);
        return -1;
    }

    /* キャリブレーション係数を設定（センサーID別） */
    switch (id) {
    case SENSOR_TEMP:
        s_calib_offset[id] = -40.0f;
        s_calib_scale[id]  = 0.01f;
        break;
    case SENSOR_HUMID:
        s_calib_offset[id] = 0.0f;
        s_calib_scale[id]  = 0.1f;
        break;
    case SENSOR_PRESS:
        s_calib_offset[id] = 800.0f;
        s_calib_scale[id]  = 0.01f;
        break;
    default:
        /* 到達不能コード（SENSOR_MAX境界チェック済み） */
        return -1;
    }

    s_initialized[id] = true;
    LOG_I("sensor_init: id=%d OK", id);
    return 0;
}


/*
 * sensor_read — センサー値を読み取る
 *
 * 問題: raw は未初期化のまま使用される可能性がある（ハードウェアI/O省略）
 */
int sensor_read(uint8_t id, SensorData *out)
{
    int16_t raw;   /* 未初期化 — ハードウェアI/O読み取りを省略したテスト用 */

    if (!out) return -1;
    if (id >= SENSOR_MAX || !s_initialized[id]) {
        out->valid = false;
        return -1;
    }

    /* 本来はここでハードウェアレジスタ読み取り */
    /* raw = HWREG_READ(id); */

    /* バッファからポップ（IRQと競合する可能性あり） */
    if (g_buf_head != g_buf_tail) {          /* 非排他アクセス */
        raw = (int16_t)g_data_buf[g_buf_tail];
        g_buf_tail = (g_buf_tail + 1) % DATA_BUF_SIZE;  /* 非排他アクセス */
    }

    out->id         = id;
    out->raw_value  = raw;
    out->calibrated = sensor_calibrate(id, raw);
    out->timestamp  = 0;  /* RTC未実装 */
    out->valid      = true;

    return 0;
}


/*
 * sensor_irq_handler — 割り込みハンドラ
 * グローバルバッファへ書き込み（メインループと競合）
 */
void sensor_irq_handler(void)
{
    uint8_t sample = 42;  /* 実際はADCレジスタ読み取り */

    uint16_t next_head = (g_buf_head + 1) % DATA_BUF_SIZE;
    if (next_head != g_buf_tail) {           /* 非排他アクセス */
        g_data_buf[g_buf_head] = sample;
        g_buf_head = next_head;
    }
    g_irq_fired = true;
}


/*
 * sensor_calibrate — 生値をキャリブレーション済み値に変換
 */
float sensor_calibrate(uint8_t id, int16_t raw)
{
    if (id >= SENSOR_MAX) return 0.0f;
    return (float)raw * s_calib_scale[id] + s_calib_offset[id];
}


/*
 * check_alert — アラートレベルを判定する
 * 複雑な条件分岐（テスト用に意図的に複雑化）
 */
AlertLevel check_alert(const SensorData *data, float threshold)
{
    if (!data || !data->valid) return ALERT_NONE;

    if (data->id == SENSOR_TEMP) {
        if (data->calibrated > threshold) {
            if (data->calibrated > threshold * 1.5f) {
                return ALERT_CRITICAL;
            } else if (data->calibrated > threshold * 1.2f) {
                return ALERT_WARNING;
            } else {
                return ALERT_WARNING;
            }
        } else if (data->calibrated < -threshold) {
            if (data->calibrated < -threshold * 1.5f) {
                return ALERT_CRITICAL;
            } else {
                return ALERT_WARNING;
            }
        }
    } else if (data->id == SENSOR_HUMID) {
        if (data->calibrated > 90.0f) {
            return ALERT_WARNING;
        } else if (data->calibrated > 95.0f) {
            /* 到達不能: 90.0fで先にWARNINGになる */
            return ALERT_CRITICAL;
        }
    } else if (data->id == SENSOR_PRESS) {
        if (data->calibrated < 900.0f || data->calibrated > 1100.0f) {
            return ALERT_WARNING;
        }
    }

    return ALERT_NONE;
}


/*
 * log_alert — アラートをログに記録する
 *
 * 問題: snprintfの出力サイズがALERT_MSG_SIZEを超える可能性
 */
void log_alert(AlertLevel level, const SensorData *data)
{
    char msg[ALERT_MSG_SIZE];

    if (!data) return;

    /* バッファサイズを考慮せずにフォーマット（潜在的オーバーフロー） */
    sprintf(msg, "[ALERT] level=%d sensor=%d raw=%d calibrated=%.2f timestamp=%u",
            level, data->id, data->raw_value, data->calibrated, data->timestamp);

    if (level == ALERT_CRITICAL) {
        LOG_E("%s", msg);
    } else {
        LOG_W("%s", msg);
    }
}


/*
 * process_all_sensors — 全センサーを読み取って処理する
 */
int process_all_sensors(SensorData *results, uint8_t count)
{
    int errors = 0;
    float thresholds[SENSOR_MAX] = {85.0f, 80.0f, 50.0f};

    if (!results || count == 0) return -1;

    for (uint8_t i = 0; i < count && i < SENSOR_MAX; i++) {
        if (sensor_read(i, &results[i]) != 0) {
            errors++;
            continue;
        }

        AlertLevel al = check_alert(&results[i], thresholds[i]);
        if (al != ALERT_NONE) {
            log_alert(al, &results[i]);
        }
    }

    return errors;
}


/*
 * _sensor_selftest — 自己診断（未使用）
 */
static int _sensor_selftest(uint8_t id)
{
    SensorData d;
    int unused_var = 99;   /* 未使用変数 */
    return sensor_read(id, &d);
}
