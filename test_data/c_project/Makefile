CC      = gcc
CFLAGS  = -Wall -Wextra -Iinclude -g
SRCS    = src/main.c src/sensor.c src/logger.c
OBJS    = $(SRCS:.c=.o)
TARGET  = sensor_monitor

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f $(OBJS) $(TARGET)

.PHONY: all clean
