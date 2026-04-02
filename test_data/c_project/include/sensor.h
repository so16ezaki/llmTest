/*
 * sensor.h — センサーデータ取得・処理インターフェース
 */

#ifndef SENSOR_H
#define SENSOR_H

#include <stdint.h>
#include <stdbool.h>

/* センサーID定義 */
#define SENSOR_TEMP    0
#define SENSOR_HUMID   1
#define SENSOR_PRESS   2
#define SENSOR_MAX     3

/* バッファサイズ */
#define DATA_BUF_SIZE  64
#define ALERT_MSG_SIZE 128

/* センサーデータ構造体 */
typedef struct {
    uint8_t  id;
    int16_t  raw_value;
    float    calibrated;
    uint32_t timestamp;
    bool     valid;
} SensorData;

/* アラートレベル */
typedef enum {
    ALERT_NONE    = 0,
    ALERT_WARNING = 1,
    ALERT_CRITICAL = 2,
} AlertLevel;

/* グローバル状態（volatileでIRQ共有） */
extern volatile uint8_t  g_data_buf[DATA_BUF_SIZE];
extern volatile uint16_t g_buf_head;
extern volatile uint16_t g_buf_tail;
extern volatile bool     g_irq_fired;

/* 関数プロトタイプ */
int  sensor_init(uint8_t id);
int  sensor_read(uint8_t id, SensorData *out);
void sensor_irq_handler(void);
float sensor_calibrate(uint8_t id, int16_t raw);
AlertLevel check_alert(const SensorData *data, float threshold);
void log_alert(AlertLevel level, const SensorData *data);
int  process_all_sensors(SensorData *results, uint8_t count);

#endif /* SENSOR_H */
