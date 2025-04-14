import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import './Camera.css';

function Camera() {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const [status, setStatus] = useState('Initializing...');
  const [intensity, setIntensity] = useState('Change Ratio: N/A (Count: 0)');
  const [laserCoords, setLaserCoords] = useState(null);
  const [warning, setWarning] = useState('');
  const [loading, setLoading] = useState(false);
  let refFrameGray = null;
  let refFrameRed = null;
  let windowTop = 0;
  let windowBottom = 0;
  let initReferenceDone = false;
  let laserDetected = false;
  let detectionCount = 0;
  let snapshotScheduled = false;
  let lastDetectionTime = 0;
  let lastSnapshotTime = 0;
  let detectedLaserCoords = null;
  const cooldownPeriod = 5;
  const rafId = useRef(null);
  let scanIndex = 0;

  const playWarningSound = () => {
    const audio = new Audio('https://www.soundjay.com/buttons/beep-01a.mp3');
    audio.play().catch(err => console.error('Audio error:', err));
  };

  useEffect(() => {
    const checkOpenCV = () => {
      if (window.cv && window.cv.Mat) {
        window.cv['onRuntimeInitialized'] = () => {
          setStatus('OpenCV.js loaded');
          startCamera();
        };
        if (window.cv.isRuntimeInitialized) {
          setStatus('OpenCV.js loaded');
          startCamera();
        }
      } else {
        setTimeout(checkOpenCV, 100);
      }
    };
    checkOpenCV();

    return () => {
      stopCamera();
    };
  }, []);

  const startCamera = () => {
    setLoading(true);
    navigator.mediaDevices
      .getUserMedia({
        video: {
          facingMode: 'environment', // Request back camera
          width: { ideal: 640 },
          height: { ideal: 480 },
        },
      })
      .then((stream) => {
        videoRef.current.srcObject = stream;
        videoRef.current.play();
        const process = () => {
          processFrame();
          rafId.current = requestAnimationFrame(process);
        };
        rafId.current = requestAnimationFrame(process);
        setStatus('Camera started');
        setLoading(false);
      })
      .catch((err) => {
        console.error('Error accessing back camera:', err);
        setStatus('Back camera error: ' + err.message);
        // Fallback to any camera
        navigator.mediaDevices
          .getUserMedia({
            video: {
              width: { ideal: 640 },
              height: { ideal: 480 },
            },
          })
          .then((stream) => {
            videoRef.current.srcObject = stream;
            videoRef.current.play();
            const process = () => {
              processFrame();
              rafId.current = requestAnimationFrame(process);
            };
            rafId.current = requestAnimationFrame(process);
            setStatus('Camera started (fallback)');
            setLoading(false);
          })
          .catch((fallbackErr) => {
            console.error('Fallback camera error:', fallbackErr);
            setStatus('No camera available: ' + fallbackErr.message);
            setLoading(false);
          });
      });
  };

  const stopCamera = () => {
    setLoading(true);
    if (videoRef.current && videoRef.current.srcObject) {
      videoRef.current.srcObject.getTracks().forEach(track => track.stop());
      videoRef.current.srcObject = null;
    }
    if (rafId.current) {
      cancelAnimationFrame(rafId.current);
      rafId.current = null;
    }
    if (refFrameGray && !refFrameGray.isDeleted()) refFrameGray.delete();
    if (refFrameRed && !refFrameRed.isDeleted()) refFrameRed.delete();
    initReferenceDone = false;
    laserDetected = false;
    detectionCount = 0;
    snapshotScheduled = false;
    lastDetectionTime = 0;
    lastSnapshotTime = 0;
    detectedLaserCoords = null;
    setStatus('Camera stopped');
    setIntensity('Change Ratio: N/A (Count: 0)');
    setLaserCoords(null);
    scanIndex = 0;
    setWarning('');
    setLoading(false);
  };

  const processFrame = () => {
    if (!videoRef.current?.videoWidth || !window.cv || !canvasRef.current) return;

    const currentTime = Date.now() / 1000;
    if (currentTime - lastSnapshotTime < cooldownPeriod) {
      detectionCount = 0;
      laserDetected = false;
      setStatus('Cooldown');
      if (!snapshotScheduled) setLaserCoords(null);
      return;
    }

    const ctx = canvasRef.current.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(videoRef.current, 0, 0, canvasRef.current.width, canvasRef.current.height);

    let frame = null;
    try {
      frame = window.cv.imread(canvasRef.current);
      if (!frame || frame.isDeleted()) {
        console.warn('Frame is invalid or deleted');
        return;
      }

      if (!initReferenceDone) {
        if (detectionCount < 10) {
          detectionCount++;
          setStatus('Initializing...');
          if (frame) frame.delete();
          return;
        }
        let refCrop = null;
        try {
          const result = detectMetalSheetWindow(frame);
          refCrop = result.croppedImage;
          windowTop = result.windowTop;
          windowBottom = result.windowBottom;
          refFrameGray = new window.cv.Mat();
          refFrameRed = new window.cv.Mat();
          window.cv.cvtColor(refCrop, refFrameGray, window.cv.COLOR_BGR2GRAY);
          let channels = new window.cv.MatVector();
          window.cv.split(refCrop, channels);
          channels.get(2).copyTo(refFrameRed);
          channels.delete();
          initReferenceDone = true;
          detectionCount = 0;
          setStatus('Reference set');
        } catch (e) {
          setStatus('Initialization error: ' + e.message);
          if (refCrop && !refCrop.isDeleted()) refCrop.delete();
          if (frame) frame.delete();
          return;
        } finally {
          if (refCrop && !refCrop.isDeleted()) refCrop.delete();
        }
      }

      let frameCrop = null;
      let grayFrame = null;
      let redFrame = null;
      let diffGray = null;
      let threshGray = null;
      let diffRed = null;
      let threshRed = null;
      let combined = null;
      let contours = null;
      let hierarchy = null;
      let laserCoord = null;

      try {
        frameCrop = frame.roi(new window.cv.Rect(0, windowTop, frame.cols, windowBottom - windowTop));
        grayFrame = new window.cv.Mat();
        redFrame = new window.cv.Mat();
        window.cv.cvtColor(frameCrop, grayFrame, window.cv.COLOR_BGR2GRAY);
        let channels = new window.cv.MatVector();
        window.cv.split(frameCrop, channels);
        channels.get(2).copyTo(redFrame);
        channels.delete();

        diffGray = new window.cv.Mat();
        threshGray = new window.cv.Mat();
        diffRed = new window.cv.Mat();
        threshRed = new window.cv.Mat();
        combined = new window.cv.Mat();
        window.cv.absdiff(refFrameGray, grayFrame, diffGray);
        window.cv.threshold(diffGray, threshGray, 50, 255, window.cv.THRESH_BINARY);
        window.cv.absdiff(refFrameRed, redFrame, diffRed);
        window.cv.threshold(diffRed, threshRed, 70, 255, window.cv.THRESH_BINARY);
        window.cv.bitwise_or(threshGray, threshRed, combined);

        let changeCount = window.cv.countNonZero(combined);
        let totalPixels = combined.size().width * combined.size().height;
        let changeRatio = changeCount / totalPixels;

        setIntensity(`Change Ratio: ${changeRatio.toFixed(3)} (Count: ${detectionCount})`);

        contours = new window.cv.MatVector();
        hierarchy = new window.cv.Mat();
        window.cv.findContours(
          combined,
          contours,
          hierarchy,
          window.cv.RETR_EXTERNAL,
          window.cv.CHAIN_APPROX_SIMPLE
        );

        if (contours.size() > 0) {
          let maxArea = 0;
          let largestContour = null;
          for (let i = 0; i < contours.size(); i++) {
            let contour = contours.get(i);
            let area = window.cv.contourArea(contour);
            if (area > maxArea) {
              maxArea = area;
              if (largestContour && !largestContour.isDeleted()) largestContour.delete();
              largestContour = contour.clone();
            }
          }
          if (largestContour) {
            let moments = window.cv.moments(largestContour);
            if (moments.m00 !== 0) {
              let cx = Math.round(moments.m10 / moments.m00);
              let cy = Math.round(moments.m01 / moments.m00);
              laserCoord = { x: cx, y: cy + windowTop };
            }
            if (largestContour && !largestContour.isDeleted()) largestContour.delete();
          }
        }

        const detectionThreshold = 0.25;
        if (changeRatio > detectionThreshold && laserCoord) {
          detectionCount++;
          if (!snapshotScheduled) setLaserCoords(laserCoord);
          if (detectionCount >= 5 && !laserDetected && !snapshotScheduled) {
            laserDetected = true;
            lastDetectionTime = currentTime;
            detectedLaserCoords = { ...laserCoord };
            setLaserCoords(detectedLaserCoords);
            setStatus('Laser detected! Snapshot in 10s');
            snapshotScheduled = true;
            setTimeout(() => takeSnapshot(), 10000);
          }
        } else {
          detectionCount = 0;
          if (laserDetected && !snapshotScheduled) {
            laserDetected = false;
            detectedLaserCoords = null;
            setLaserCoords(null);
          }
        }

        if (!snapshotScheduled) setStatus(laserDetected ? 'Laser detected' : 'No detection');

      } finally {
        if (contours && !contours.isDeleted()) contours.delete();
        if (hierarchy && !hierarchy.isDeleted()) hierarchy.delete();
        if (combined && !combined.isDeleted()) combined.delete();
        if (threshRed && !threshRed.isDeleted()) threshRed.delete();
        if (diffRed && !diffRed.isDeleted()) diffRed.delete();
        if (threshGray && !threshGray.isDeleted()) threshGray.delete();
        if (diffGray && !diffGray.isDeleted()) diffGray.delete();
        if (redFrame && !redFrame.isDeleted()) redFrame.delete();
        if (grayFrame && !grayFrame.isDeleted()) grayFrame.delete();
        if (frameCrop && !frameCrop.isDeleted()) frameCrop.delete();
      }
    } catch (e) {
      setStatus('Processing error: ' + e.message);
    } finally {
      if (frame && !frame.isDeleted()) frame.delete();
    }
  };

  const detectMetalSheetWindow = (frame) => {
    let gray = new window.cv.Mat();
    window.cv.cvtColor(frame, gray, window.cv.COLOR_BGR2GRAY);
    let blurred = new window.cv.Mat();
    window.cv.GaussianBlur(gray, blurred, new window.cv.Size(7, 7), 0);
    let edges = new window.cv.Mat();
    window.cv.Canny(blurred, edges, 30, 150);
    let kernel = window.cv.Mat.ones(3, 3, window.cv.CV_8U);
    let dilated = new window.cv.Mat();
    window.cv.dilate(edges, dilated, kernel);
    let lines = new window.cv.Mat();
    window.cv.HoughLinesP(dilated, lines, 1, Math.PI / 180, 50, frame.cols / 3, 10);
    let metalSheetY = null;
    if (lines.rows > 0) {
      let horizontalLines = [];
      for (let i = 0; i < lines.rows; i++) {
        let line = [
          lines.data32S[i * 4],
          lines.data32S[i * 4 + 1],
          lines.data32S[i * 4 + 2],
          lines.data32S[i * 4 + 3],
        ];
        if (Math.abs(line[1] - line[3]) < 10) horizontalLines.push(line);
      }
      if (horizontalLines.length > 0) {
        horizontalLines.sort((a, b) => Math.abs(b[2] - b[0]) - Math.abs(a[2] - a[0]));
        let line = horizontalLines[0];
        metalSheetY = Math.floor((line[1] + line[3]) / 2);
      }
    }
    if (metalSheetY === null) throw new Error('Could not detect metal sheet');
    const A = 50, B = 50;
    let windowTop = Math.max(0, metalSheetY - A);
    let windowBottom = Math.min(frame.rows, metalSheetY + B);
    let croppedImage = frame.roi(new window.cv.Rect(0, windowTop, frame.cols, windowBottom - windowTop));
    [lines, dilated, kernel, edges, blurred, gray].forEach(mat => {
      if (mat && !mat.isDeleted()) mat.delete();
    });
    return { croppedImage, windowTop, windowBottom };
  };

  const takeSnapshot = async () => {
    setLoading(true);
    const ctx = canvasRef.current.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(videoRef.current, 0, 0, canvasRef.current.width, canvasRef.current.height);
    const dataUrl = canvasRef.current.toDataURL('image/jpeg');
    const timestamp = Math.floor(Date.now() / 1000);
    const blob = await fetch(dataUrl).then(res => res.blob());
    const file = new File([blob], `snapshot_${timestamp}.jpg`, { type: 'image/jpeg' });

    const angles = JSON.parse(localStorage.getItem('angles') || '[]');
    const expectedAngle = scanIndex < angles.length ? angles[scanIndex] : null;
    const formData = new FormData();
    formData.append('snapshot', file);
    formData.append('coordinates', JSON.stringify(detectedLaserCoords || {}));
    formData.append('expectedAngle', expectedAngle !== null ? expectedAngle.toString() : '');

    try {
      const response = await axios.post('https://laserbending.onrender.com/auth/save-snapshot', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setStatus('Snapshot saved and sent');
      if (response.data.warning) {
        setWarning(response.data.warning);
        playWarningSound();
      } else {
        setWarning('');
      }
    } catch (error) {
      setStatus('Snapshot saved, network error');
    }
    snapshotScheduled = false;
    lastSnapshotTime = Date.now() / 1000;
    laserDetected = false;
    detectionCount = 0;
    scanIndex += 1;
    setStatus('Snapshot saved');
    setLoading(false);
  };

  return (
    <div className="camera-page">
      <h1 className="camera-page-title">Laser Detection</h1>
      <div className="camera-page-card">
        <div className="camera-page-card-body">
          <video ref={videoRef} width="640" height="480" className="camera-page-video-feed" />
          <canvas ref={canvasRef} width="640" height="480" style={{ display: 'none' }} />
          <p className="camera-page-status-text">Status: {status}</p>
          <p className="camera-page-intensity-text">Intensity: {intensity}</p>
          {laserCoords && (
            <p className="camera-page-coords-text">Laser Coordinates: ({laserCoords.x}, {laserCoords.y})</p>
          )}
          {warning && <p className="camera-page-warning-text">Warning: {warning}</p>}
          <div className="camera-page-button-group">
            <button onClick={startCamera} className="camera-page-btn camera-page-btn-primary" disabled={loading}>
              Start Camera
            </button>
            <button onClick={stopCamera} className="camera-page-btn camera-page-btn-danger" disabled={loading}>
              Stop Camera
            </button>
            <a href="/" className="camera-page-btn camera-page-btn-secondary">
              Back
            </a>
          </div>
          {loading && (
            <div className="camera-page-spinner-border text-primary" role="status">
              <span className="visually-hidden">Loading...</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default Camera;