# Image update implementation baseline

This file records verified context for continuing the work in `../ATOMAR_IMAGE.md`.

## Server configuration

See [`../panel-test/SERVER_OPERATIONS.md`](../panel-test/SERVER_OPERATIONS.md) for the production directory layout, systemd unit, Nginx route, publication commands, and confirmed HTTP checks.

## Firmware baseline reviewed on 2026-11-17

- Firmware checkout: `9bc585dd468f418c0253801af26ec03ed2993ec7`.
- The checkout has a user-local progress marker in `src/types.h`: `SOFTWARE_VERSION` is `0.1.0c`. Preserve it.
- The attached `build.ps1 -Upload` transcript confirms a successful `epd13` build and upload to COM10 on 2026-11-17. PlatformIO Core was 6.1.19, pioarduino ESP32 platform 55.03.37, Arduino-ESP32 3.3.7, and the selected board was `esp32-c6-devkitm-1`.
- PlatformIO reports 4 MB of ESP32 internal flash. This is distinct from the external SPI SerialFlash used for image files.
- The local SerialFlash dependency is commit `13f477b8a39f9c5b61f540568f976f8a959ae3af`, version 0.6.0. It matches the version recorded in the plan. Source inspection confirms `remove()` only clears the directory hash and does not free flash space.
- The configured NVS partition is `0x5000` bytes (20 KiB), at offset `0x9000`.
- For `epd13`, the stored raster is 1200 × 1600 pixels at 4 bits per pixel. `IMAGE_SLOT_SIZE` is `1600 * 1200 / 2 + 4096 = 964096` bytes. Two slots require 1,928,192 bytes before directory, download, and migration-backup space.
- `MAX_DOWNLOAD_SIZE` has a 6 MiB ceiling. The download path now uses the existing `tmp_raw.bin` allocation, capped to that limit. It no longer reallocates files or erases SerialFlash block 0 on failure.
- Before this task, the current `debugFS()` reported SPIFFS usage and heap only. A read-only startup diagnostic has now been added after SerialFlash initialization; it logs JEDEC ID/capacity, erase-block size, every directory file's address and size, free tail space, and NVS entry counts.
- The diagnostic and Phase 1 changes built successfully for `epd13` (Flash 91.6%, RAM 62.8%) and `epd7` (Flash 90.9%, RAM 39.4%) using the checked-in platform and library versions. No firmware was uploaded by this task.
- The current upstream reference was consulted at `https://github.com/paperlesspaper/paperlesspaper-firmware-offline` and its `src/main.cpp`. It documents the supported image modes and image-download behavior; the local firmware has additional changes, so the local source remains the implementation baseline.

## P01 status

One epd13 device reported the following values on 2026-11-17:

| Region or file | Start | Length | End |
| --- | ---: | ---: | ---: |
| SerialFlash directory block | 0 | 65,536 | 65,536 |
| `tmp.bmp` (current display slot) | 65,536 | 983,040 | 1,048,576 |
| `tmp_raw.bin` (download slot) | 6,815,744 | 6,291,456 | 13,107,200 |
| Free tail after last allocation | 13,107,200 | 3,670,016 | 16,777,216 |

The external flash is 16,777,216 bytes with 65,536-byte erase blocks. The JEDEC ID reported by the device is `EF 40 18 00 00`. The SerialFlash report computes free tail from the last allocated file; the gap between the end of `tmp.bmp` and the start of `tmp_raw.bin` is not counted as reusable space.

For epd13, one image slot is 964,096 logical bytes and rounds to 983,040 bytes (15 erase blocks). A second slot can fit after the existing download slot at address 13,107,200 and would end at 14,090,240, leaving 2,686,976 bytes at the tail. A 15-block migration backup can be reserved at address 15,794,176 through the end of flash; it is separate from the current directory, image slots, and download file. This leaves a 26-block gap after slot B. The current 6 MiB download allocation, directory block, two 15-block image slots, and one 15-block backup use 142 of 256 erase blocks (9,306,112 bytes total).

NVS statistics: 210 entries used, 420 free, 294 available for new data, 630 total, and 6 namespaces. The NVS partition is 20 KiB.

Source, build configuration, partition table, local dependency commit, supplied build/upload transcript, and the read-only device measurements are checked for this epd13 unit. The measured free tail was enough to create slot B once without a directory rebuild. The follow-up device log confirms `tmp_b.bmp` at address 13,107,200 with size 983,040 bytes; the reserved backup area starts at 15,794,176. Firmware appends `tmp_b.bmp` only when it can prove the SerialFlash allocation order and reserve a separate 15-block migration area; otherwise it logs and stays in single-slot mode. Other physical flash variants still need their own diagnostic before using this layout.

The diagnostic firmware used for the report builds for both `epd13` and `epd7`; the attached runtime log came from the user's already-connected epd13 unit. Do not infer external SerialFlash size from the ESP32's separate 4 MB internal-flash report.

## P02 format and settings decisions

- HTTP image body limit: at most 6,291,456 bytes (6 MiB), and never larger than the actual preallocated download slot. The measured device has a 6 MiB download slot. Do not force a minimum download area when calculating a smaller device's capacity.
- Accepted source formats: JPEG; uncompressed BMP at 4, 24, or 32 bits per pixel; and raw 4-bit panel raster. For 32-bit BMP, accept BI_RGB and BI_BITFIELDS only with supported channel masks. Content-Type is advisory; detect and validate the byte format.
- Width and height for JPEG/BMP: each dimension must be from 1 through 16,384. `INT32_MIN` BMP height is invalid. Larger valid images within these bounds may be proportionally scaled as today.
- Progressive JPEG remains accepted with the current decoder behavior (first scan at one-eighth resolution); baseline JPEG is recommended for full resolution.
- Raw raster has no container header and must be exactly `IMG_WIDTH * IMG_HEIGHT / 2` bytes: 192,000 for epd7 and 960,000 for epd13. Each nibble must be one of 0, 1, 2, 3, 5, or 6. Nibble 4 and other values are invalid.
- Digest option name: `requireImageDigest`, false by default (`digest-optional`). Store it as a 32-bit integer 0/1 at `EEPROM_SETTINGS_ADR + 820` (absolute EEPROM offset 1320). This follows the existing positional EEPROM settings layout; `autoRotation` occupies `+815..+818`, so the new field does not overlap it. Missing or any value other than 1 restores the optional default.
- The RAW exact-size and nibble checks are now implemented for downloaded and BLE-staged rasters. `requireImageDigest` persistence is present with the optional default, but HTTP digest enforcement is still pending.

## Phase 1 implementation status

- `openSlot()` opens preallocated files only. The former automatic allocation/retry path that could erase directory block 0 has been removed from normal firmware paths.
- Startup may append `tmp_b.bmp` once after a verified last allocation, provided a slot and a reserved migration area fit. No directory rebuild or formatting is attempted. Single-slot mode remains a deliberate fallback.
- HTTP images are converted to the inactive slot when Slot B is available. The active slot and its new validator are saved together in one EEPROM commit after conversion succeeds.
- JPEG output is not erased until the source opens and dimensions are bounded. BMP output is erased after header/palette checks. Raw raster size and color nibbles are checked before output erase. Raster writes, short reads, and flash-ready waits now propagate failure.
- BLE raster data is staged in `tmp_raw.bin`; it is copied to the candidate image slot only after byte count, CRC/readback, and raster validation pass. Slot selection and BLE mode are committed together.
- ETag comparison takes precedence over Last-Modified. Factory reset erases contents of both image slots without removing or recreating directory entries.
- Static review and builds: `platformio run -e epd13` succeeded (Flash 91.6%, RAM 62.8%); `platformio run -e epd7` succeeded (Flash 90.9%, RAM 39.4%). The only compile warning is the existing SdFat `File not defined because __has_include(FS.h)` warning. `git diff --check` passed before the most recent edits and will be repeated.
- The device log confirms slot B allocation and reuse across reboot. It also shows an HTTP 304 response followed by rendering the local slot. Hardware validation remains open for failed-conversion preservation, BLE upload, single-slot fallback, and reset timing.

The device log supplied before this phase reported a 16 MiB SerialFlash with 64 KiB erase blocks, a 6 MiB `tmp_raw.bin`, and 3,670,016 free tail bytes. Firmware has been built but not uploaded with the one-time Slot B append path; use the normal diagnostic log to verify its resulting address before relying on A/B operation.

## Phase 2 implementation status

- Image error text is rendered as foreground pixels over the stored raster on epd7. For epd13, the text is rasterized into a small monochrome mask and merged into the outgoing raster chunks; the saved image bytes are never modified.
- The text uses the exact required string and computes its drawing direction as the existing text rotation plus 90 degrees relative to the picture rotation. Its position is near the upper-left corner with a small margin. The 7-inch path draws opaque glyph cells with white background; the 13-inch path merges a narrow white backing mask and black glyph mask into outgoing chunks. Since the 13-inch panel is landscape while its streamed raster axes are rotated, the physical upper-left position maps near the right edge of stream coordinates.
- Presentation state tracks desired content, last completed content, and pending render. A distinct EEPROM display marker identifies the new error overlay. The marker is updated only after the panel busy signal reports completion.
- A failed update preserves `settings.lastModified`. A later HTTP 304 or unchanged HTTP 200 removes a completed error overlay by restoring its region from the active image slot on epd13. A legacy full-screen error and epd7 use a full local render. Repeated errors skip a refresh only after a completed overlay is known.
- Builds after Phase 2: `epd13` succeeded (Flash 91.8%, RAM 62.8%); `epd7` succeeded (Flash 90.9%, RAM 39.4%). Existing SdFat include warning remains.
- The user confirmed epd13 text angle, readability, upper-left position, and the revised partial overlay. Open hardware checks include the latest white-backing extension, partial HTTP 304/unchanged-200 recovery, no-image fallback, repeated-error refresh behavior, and epd7 appearance.

## epd13 partial refresh

- Goal: render the error message by refreshing its small rectangle while preserving the rest of the image. A full-screen refresh does not satisfy this requirement. The selected driver's capability flags alone do not prove that its partial-refresh sequence works on this panel.
- Device tests on 2026-11-17: the original window-refresh call made the error text visible but faded colors from left to right outside the text. A direct SPI window stream then made the text disappear. That stream read SerialFlash while the panel chip select was LOW on the same SPI bus, contaminating the panel transfer with flash traffic. The earlier explanation that native color values alone caused this was not established.
- `src/epaper_partial_13.cpp` reads the complete aligned region into RAM before any panel transfer. It translates saved colors to the standard GxEPD2 palette and uses `writeImage()` for the bounded write. It never clears full controller RAM. The previously reported window was x=1124, y=32, w=32, h=564 (9,024 bytes). The revised white backing includes the actual glyph bounds plus padding and preserves the old backing extent, so the window can grow slightly beyond that original size.
- After the data writes, both controllers receive CMD66 and PTLW. X/width are aligned to four pixels; Y/height are even. The other controller receives a minimum 16x2 companion window (16 bytes), populated from the stored image because controller RAM may have been lost during sleep/reset. Both controllers must participate in the shared BUSY/DRF handshake; this adds a 32-pixel refresh outside the text rectangle.
- The refresh uses PON, a readiness wait and 30 ms delay, DRF with payload **0x01**, completion wait, power off, and PTLW cleanup after 300 ms. This avoids the original driver's **0x00** DRF and invalid 2x2 companion width. The user confirmed this sequence works on the EL133UF3 unit (photo 5421.jpg). Normal image updates retain their existing full refresh. The overlay has no automatic full-refresh fallback.
- On recovery, `showStoredImage(fileName, sourceUnchanged)` selects partial restoration only when the previous completed presentation is `DISPLAY_ERROR_OVERLAY` and the download result is `DL_NOT_MODIFIED` (HTTP 304 or matching-validator HTTP 200). The same expanded window is filled with original source pixels, without composing the glyph or white mask. This path also skips the debug CRC scan of the entire image slot. New image data, BLE APPLY, legacy full-screen errors, and epd7 still receive a full render. The persistent presentation marker is changed to `DISPLAY_PICTURE` only after successful completion; failures remain pending and can retry after sleep/reset.
- Sources consulted: [paperlesspaper render path](https://github.com/paperlesspaper/paperlesspaper-firmware-offline/blob/main/src/epaper_display.cpp), [selected GxEPD2 driver](https://github.com/smarthomeagentur/GxEPD2/blob/master/src/epd7c/GxEPD2_1330c_EL133UF3.cpp), [13.3-inch Spectra 6 controller sequence](https://github.com/philippwaller/esphome-epaper-spectra6-133/blob/main/components/epaper_spectra6_133/epaper_spectra6_133_controller.cpp). The last implementation targets GDEP133C02/T133A01; it is supporting evidence, not hardware validation of EL133UF3.
- Host validation: `python tests/run_partial_overlay_host.py` compiles the production region and presentation functions with simulated hardware. All 38 cases pass: 24 cover show/restore pixels, padding beyond the last glyph, preservation of the old backing area, both controller halves, rotation, RAW/BMP offsets, colors, protocol order, failed reads, invalid data, empty masks and timeout. Seven cases per panel check unchanged/new source routing, old full-screen errors, pending retries, failure state preservation, and explicit image rendering. These checks do not simulate ink or analog behavior.
- Current firmware validation, including partial recovery and expanded backing: both builds passed: `epd13` Flash 91.9%, RAM 62.8%; `epd7` Flash 90.9%, RAM 39.4%. `esptool --chip esp32c6 image-info` reports a valid epd13 image checksum and validation hash; the binary is 1,805,936 bytes and fits the 1,900,544-byte app partition. The existing SdFat include warning remains. Earlier Windows path-error builds were sandbox failures; the current builds ran with explicit permission outside the filesystem sandbox.

Device validation for this revision:

1. Build and upload the current epd13 firmware with `./build.ps1 -Upload -Monitor` after closing any existing serial monitor.
2. Keep the image server reachable for one normal image render first, to restore saturated colors and clear any previous error presentation.
3. Make the image request fail (for example HTTP 502), then trigger the next scheduled update. Expect `[EPD] Partial overlay show: ...; companion=16x2; DRF=0x01`, followed by `[EPD] Partial overlay show complete.` and `[EPD] Set Image Done: 0`. Check that white padding extends beyond the final letter. The new window is slightly longer to include that padding.
4. Check that the text is visible at the landscape upper-left, that the main color fields remain saturated, and that only the text rectangle visibly refreshes. The companion window restores the same source pixels and should not alter the final image there. The 40-second class of refresh duration is not a failure by itself.
5. Leave the request failing for another wake cycle: the completed overlay should not refresh again. Restore the server without changing the image or ETag. On the next ordinary wake, expect `[DL] Image unchanged (HTTP 304); skipping download.` or the matching-validator HTTP 200 message, then `[IMAGE] Source unchanged; restoring only the error overlay region.` and `[EPD] Partial overlay restore: ...`. Only the error rectangle and companion window should refresh. Confirm that the white backing and every letter disappear, including remnants of the previous shorter backing. Do not use a forced-download button action for this check.
6. Repeat with a genuinely changed image/ETag while the overlay is visible: the new image must receive a full refresh. A further unchanged successful wake should skip rendering completely.

Partial overlay display without the previous fading is confirmed by the user. The enlarged white backing and partial recovery still require the next device check. No upload was performed by the assistant for this revision.

Earlier device checks confirmed changed-image detection, outage overlays, and recovery with a full local render. The monitor log confirms slot B at address 13,107,200. Subsequent photos confirm the corrected +90-degree text, white backing and physical upper-left position. Photo 5421.jpg and the user's report confirm successful partial overlay rendering without the old color fading. The latest backing extension and partial recovery are the remaining device checks for this revision.

