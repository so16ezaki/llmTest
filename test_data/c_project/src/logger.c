/*
 * logger.c — ログ出力実装
 */

#include <stdio.h>
#include <stdarg.h>
#include <time.h>
#include "logger.h"

LogLevel g_log_level = LOG_INFO;

static const char *s_level_str[] = {"DEBUG", "INFO", "WARN", "ERROR"};

static FILE *s_log_file = NULL;


void logger_init(LogLevel level)
{
    g_log_level = level;
    s_log_file = stderr;
}


void logger_write(LogLevel level, const char *fmt, ...)
{
    if (level < g_log_level) return;
    if (!s_log_file) s_log_file = stderr;

    va_list ap;
    va_start(ap, fmt);
    fprintf(s_log_file, "[%s] ", s_level_str[level]);
    vfprintf(s_log_file, fmt, ap);
    fprintf(s_log_file, "\n");
    va_end(ap);
}


void logger_flush(void)
{
    if (s_log_file) {
        fflush(s_log_file);
    }
}
