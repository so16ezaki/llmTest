/*
 * main.c — センサーモニタリングシステム エントリーポイント
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sensor.h"
#include "logger.h"

#define POLL_INTERVAL_MS  100
#define MAX_ERRORS        5


/*
 * init_system — システム全体の初期化
 */
static int init_system(void)
{
    logger_init(LOG_INFO);
    LOG_I("System starting...");

    int failed = 0;
    for (uint8_t i = 0; i < SENSOR_MAX; i++) {
        if (sensor_init(i) != 0) {
            LOG_E("Failed to init sensor %d", i);
            failed++;
        }
    }

    if (failed > 0) {
        LOG_W("%d sensor(s) failed to initialize", failed);
    }

    return failed;
}


/*
 * run_monitor — メインモニタリングループ
 */
static void run_monitor(int max_cycles)
{
    SensorData readings[SENSOR_MAX];
    int error_count = 0;
    int cycle = 0;

    LOG_I("Monitor loop started (max_cycles=%d)", max_cycles);

    while (max_cycles <= 0 || cycle < max_cycles) {
        int errs = process_all_sensors(readings, SENSOR_MAX);

        if (errs > 0) {
            error_count += errs;
            LOG_W("Cycle %d: %d error(s), total=%d", cycle, errs, error_count);
        }

        if (error_count >= MAX_ERRORS) {
            LOG_E("Too many errors (%d), aborting", error_count);
            break;
        }

        cycle++;

        /* 簡易スリープ（実際はRTOSタスク遅延） */
        for (volatile int i = 0; i < POLL_INTERVAL_MS * 1000; i++);
    }

    LOG_I("Monitor loop ended after %d cycles", cycle);
}


/*
 * print_summary — 結果サマリー出力
 */
static void print_summary(const SensorData *data, uint8_t count)
{
    printf("=== Sensor Summary ===\n");
    for (uint8_t i = 0; i < count; i++) {
        if (data[i].valid) {
            printf("  Sensor[%d]: raw=%d  calibrated=%.2f\n",
                   data[i].id, data[i].raw_value, data[i].calibrated);
        } else {
            printf("  Sensor[%d]: N/A\n", i);
        }
    }
}


int main(int argc, char *argv[])
{
    int max_cycles = 10;

    if (argc > 1) {
        max_cycles = atoi(argv[1]);
    }

    if (init_system() == SENSOR_MAX) {
        fprintf(stderr, "Fatal: all sensors failed\n");
        return EXIT_FAILURE;
    }

    run_monitor(max_cycles);

    /* 最終読み取り */
    SensorData final_data[SENSOR_MAX];
    process_all_sensors(final_data, SENSOR_MAX);
    print_summary(final_data, SENSOR_MAX);

    logger_flush();
    return EXIT_SUCCESS;
}
