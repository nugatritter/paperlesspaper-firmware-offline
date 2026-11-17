#pragma once

#ifdef EPD_TYPE_13INCH

#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <SPI.h>
#include <SerialFlash.h>

bool padImageErrorBackground13(GFXcanvas1 &textMask, GFXcanvas1 &backgroundMask);

bool writeImageErrorRegion13(SPIClass &spi, SerialFlashFile &image, uint32_t imageOffset,
                            GFXcanvas1 &textMask, GFXcanvas1 &backgroundMask,
                            int maskLeft, int maskTop, bool rotate180, bool doRefresh, bool showOverlay);

#endif
