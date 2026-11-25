#pragma once

#ifdef EPD_TYPE_13INCH

#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <SPI.h>
#include <SerialFlash.h>

bool padImageErrorBackground13(GFXcanvas1 &textMask, GFXcanvas1 &backgroundMask);

// Turns both masks and their panel position with the picture when it is rotated by 180 degrees.
void orientImageErrorMasks13(GFXcanvas1 &textMask, GFXcanvas1 &backgroundMask, bool rotate180,
                             int &maskLeft, int &maskTop);

bool writeImageErrorRegion13(SPIClass &spi, SerialFlashFile &image, uint32_t imageOffset,
                            GFXcanvas1 &textMask, GFXcanvas1 &backgroundMask,
                            int maskLeft, int maskTop, bool rotate180, bool doRefresh, bool showOverlay, bool blankBacking = false);

bool writeImageQuarter13(SPIClass &spi, SerialFlashFile &candidate, uint32_t candidateOffset,
                         SerialFlashFile &previous, uint32_t previousOffset, bool rotate180, unsigned quarter);

#endif
