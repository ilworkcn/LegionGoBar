// Thin C wrapper around Jibb Smart's GamepadMotionHelpers (MIT-licensed,
// vendored as GamepadMotion.hpp in this directory). Only the subset of the
// API we currently consume from the managed side is exported.
//
// Symbol shape mirrors HandheldCompanion's wrapper so the P/Invoke surface
// on the C# side reads naturally.

#include "GamepadMotion.hpp"

#define GMEXPORT extern "C" __declspec(dllexport)

GMEXPORT GamepadMotion* CreateGamepadMotion()
{
    return new GamepadMotion();
}

GMEXPORT void DeleteGamepadMotion(GamepadMotion* motion)
{
    delete motion;
}

GMEXPORT void ResetGamepadMotion(GamepadMotion* motion)
{
    if (motion) motion->Reset();
}

GMEXPORT void ProcessMotion(
    GamepadMotion* motion,
    float gyroX, float gyroY, float gyroZ,
    float accelX, float accelY, float accelZ,
    float deltaTime)
{
    if (motion) motion->ProcessMotion(gyroX, gyroY, gyroZ, accelX, accelY, accelZ, deltaTime);
}

GMEXPORT void GetCalibratedGyro(GamepadMotion* motion, float* x, float* y, float* z)
{
    if (motion && x && y && z) motion->GetCalibratedGyro(*x, *y, *z);
}

GMEXPORT void GetGravity(GamepadMotion* motion, float* x, float* y, float* z)
{
    if (motion && x && y && z) motion->GetGravity(*x, *y, *z);
}

GMEXPORT void GetProcessedAcceleration(GamepadMotion* motion, float* x, float* y, float* z)
{
    if (motion && x && y && z) motion->GetProcessedAcceleration(*x, *y, *z);
}

GMEXPORT void GetOrientation(GamepadMotion* motion, float* w, float* x, float* y, float* z)
{
    if (motion && w && x && y && z) motion->GetOrientation(*w, *x, *y, *z);
}

GMEXPORT void GetPlayerSpaceGyro(GamepadMotion* motion, float* x, float* y, float yawRelaxFactor)
{
    if (motion && x && y) motion->GetPlayerSpaceGyro(*x, *y, yawRelaxFactor);
}

GMEXPORT void GetWorldSpaceGyro(GamepadMotion* motion, float* x, float* y, float sideReductionThreshold)
{
    if (motion && x && y) motion->GetWorldSpaceGyro(*x, *y, sideReductionThreshold);
}

GMEXPORT void StartContinuousCalibration(GamepadMotion* motion)
{
    if (motion) motion->StartContinuousCalibration();
}

// JSL CalibrationMode is a flags enum (Manual=0, Stillness=1, SensorFusion=2).
// Pass `1` for stillness-detection-only auto calibration; `3` for the combined
// stillness + sensor-fusion path; `0` to disable. We surface this so the
// managed wrapper can put JSL into auto-calibration without using the
// misleadingly-named StartContinuousCalibration (which is actually a manual
// "hold still and capture" mode).
GMEXPORT void SetCalibrationMode(GamepadMotion* motion, int calibrationMode)
{
    if (motion) motion->SetCalibrationMode(static_cast<GamepadMotionHelpers::CalibrationMode>(calibrationMode));
}

GMEXPORT void PauseContinuousCalibration(GamepadMotion* motion)
{
    if (motion) motion->PauseContinuousCalibration();
}

GMEXPORT void ResetContinuousCalibration(GamepadMotion* motion)
{
    if (motion) motion->ResetContinuousCalibration();
}

GMEXPORT void GetCalibrationOffset(GamepadMotion* motion, float* xOffset, float* yOffset, float* zOffset)
{
    if (motion && xOffset && yOffset && zOffset)
        motion->GetCalibrationOffset(*xOffset, *yOffset, *zOffset);
}

GMEXPORT void SetCalibrationOffset(GamepadMotion* motion, float xOffset, float yOffset, float zOffset, int weight)
{
    if (motion) motion->SetCalibrationOffset(xOffset, yOffset, zOffset, weight);
}

GMEXPORT float GetAutoCalibrationConfidence(GamepadMotion* motion)
{
    return motion ? motion->GetAutoCalibrationConfidence() : 0.0f;
}

GMEXPORT bool GetAutoCalibrationIsSteady(GamepadMotion* motion)
{
    return motion ? motion->GetAutoCalibrationIsSteady() : false;
}
