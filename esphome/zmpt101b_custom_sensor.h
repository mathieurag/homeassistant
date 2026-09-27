#include "esphome.h"
#include <Arduino.h>

#define VMAX 250
#define FREQUENCY 50
#define CALIBRATE_READ 1700
#define CALIBRATE_ACTUAL 240
#define ZERO_VAC 2700

class ZMPT101BSensor : public PollingComponent, public Sensor {
 public:
  // constructor
  ZMPT101BSensor() : PollingComponent(10000) {}

  float get_setup_priority() const override { return esphome::setup_priority::HARDWARE; }

  void setup() override {
    // This will be called by App.setup()
  }

  void update() override {
  // This will be called every "update_interval" milliseconds.

    uint32_t period = 1000000 / FREQUENCY;
    uint32_t t_start = micros();
    uint32_t Vsum = 0, measurements_count = 0;
    int32_t Vnow;

    while (micros() - t_start < period) {
      Vnow = analogRead(A4) - ZERO_VAC;
      Vsum += Vnow*Vnow;
      measurements_count++;
    }

    float Vrms = sqrt(Vsum / measurements_count) / CALIBRATE_READ * CALIBRATE_ACTUAL-5;
    publish_state(int(abs(Vrms)));

  }
};