/*
 * logger.h — ログ出力インターフェース
 */

#ifndef LOGGER_H
#define LOGGER_H

#include <stdint.h>

typedef enum {
    LOG_DEBUG = 0,
    LOG_INFO  = 1,
    LOG_WARN  = 2,
    LOG_ERROR = 3,
} LogLevel;

extern LogLevel g_log_level;

void logger_init(LogLevel level);
void logger_write(LogLevel level, const char *fmt, ...);
void logger_flush(void);

#define LOG_D(fmt, ...) logger_write(LOG_DEBUG, fmt, ##__VA_ARGS__)
#define LOG_I(fmt, ...) logger_write(LOG_INFO,  fmt, ##__VA_ARGS__)
#define LOG_W(fmt, ...) logger_write(LOG_WARN,  fmt, ##__VA_ARGS__)
#define LOG_E(fmt, ...) logger_write(LOG_ERROR, fmt, ##__VA_ARGS__)

#endif /* LOGGER_H */
