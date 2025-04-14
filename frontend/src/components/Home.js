import React, { useState, useRef } from 'react';
import axios from 'axios';
import './Home.css';

function Home() {
  const [dxfInfo, setDxfInfo] = useState(null);
  const [numScans, setNumScans] = useState('');
  const [angles, setAngles] = useState('');
  const [laserParams, setLaserParams] = useState([]);
  const [gcode, setGcode] = useState('');
  const [loading, setLoading] = useState(false); // Single loading state for all actions
  const [copied, setCopied] = useState(false);
  const [uploadedFileName, setUploadedFileName] = useState('');
  const fileInputRef = useRef(null);

  const uploadFile = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setUploadedFileName(file.name);
    const formData = new FormData();
    formData.append('file', file);
    setLoading(true);
    try {
      const res = await axios.post('https://laserbending.onrender.com/auth/handle-dxf', formData);
      if (res.data.success) {
        setDxfInfo(res.data.dxf_info);
      } else {
        alert('Upload failed: ' + res.data.message);
      }
    } catch (err) {
      alert('Error: ' + err.message);
    }
    setLoading(false);
  };

  const triggerFileInput = () => {
    fileInputRef.current.click();
  };

  const submitScans = async () => {
    if (!dxfInfo || !numScans) {
      alert('Upload DXF and enter scans!');
      return;
    }
    setLoading(true);
    const n = parseInt(numScans);
    if (n < 1) {
      setLoading(false);
      return;
    }
    const startAngle = (parseFloat(dxfInfo['Start angle']) * Math.PI) / 180;
    const endAngle = (parseFloat(dxfInfo['End angle']) * Math.PI) / 180;
    const angles = Array.from({ length: n }, (_, i) => startAngle + ((endAngle - startAngle) * i) / (n - 1));
    const x = angles.map((a) => dxfInfo.Center[0] + dxfInfo.Radius * Math.cos(a));
    const y = angles.map((a) => dxfInfo.Center[1] + dxfInfo.Radius * Math.sin(a));
    const adjustedAngles = [];
    for (let i = 0; i < x.length - 1; i++) {
      const dx = x[i + 1] - x[i];
      const dy = y[i + 1] - y[i];
      adjustedAngles.push((180 - (Math.atan2(dy, dx) * 180) / Math.PI).toFixed(2));
    }
    setAngles(adjustedAngles.join(', '));
    localStorage.setItem('angles', JSON.stringify(adjustedAngles));
    setLoading(false);
  };

  const getLaserParams = async () => {
    if (!angles) {
      alert('Submit scans first!');
      return;
    }
    setLoading(true);
    const anglesArray = angles.split(',').map((a) => parseFloat(a.trim()));
    try {
      const res = await axios.post('https://laserbending.onrender.com/auth/predict', { angles: anglesArray });
      if (res.status === 200) {
        setLaserParams(res.data);
      } else {
        alert('Prediction failed: ' + res.data.message);
      }
    } catch (err) {
      alert('Error: ' + err.message);
    }
    setLoading(false);
  };

  const getGcode = async () => {
    setLoading(true);
    try {
      const anglesArray = angles.split(',').map((a) => parseFloat(a.trim()));
      const res = await axios.post('https://laserbending.onrender.com/auth/generate-gcode', { angles: anglesArray });
      if (res.data && res.data.gcode) {
        setGcode(res.data.gcode);
      } else {
        alert('G-code failed: ' + (res.data.message || 'Unknown error'));
      }
    } catch (err) {
      alert('Error: ' + err.message);
    }
    setLoading(false);
  };

  const copyToClipboard = () => {
    if (!gcode) return;
    navigator.clipboard.writeText(gcode).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="home-container">
      <h1 className="home-title">Laser Bending Application</h1>
      <div className="row g-5">
        {/* Left Column */}
        <div className="col-lg-6 col-md-12">
          {/* DXF Upload Card */}
          <div className="card custom-card">
            <div className="card-body">
              <h5 className="card-title">Upload DXF</h5>
              <input
                type="file"
                accept=".dxf"
                onChange={uploadFile}
                className="d-none"
                ref={fileInputRef}
                disabled={loading}
              />
              <button
                onClick={triggerFileInput}
                className="btn btn-upload w-100 mb-4"
                disabled={loading}
              >
                <span className="upload-icon">📤</span> Upload DXF
              </button>
              {uploadedFileName && (
                <div className="file-name-box">
                  <span className="file-name">File: {uploadedFileName}</span>
                </div>
              )}
              {loading && (
                <div className="spinner-border text-primary" role="status">
                  <span className="visually-hidden">Loading...</span>
                </div>
              )}
              {dxfInfo && (
                <div className="dxf-info">
                  <p>
                    <strong>Center:</strong> ({parseFloat(dxfInfo.Center[0]).toFixed(3)},{' '}
                    {parseFloat(dxfInfo.Center[1]).toFixed(3)})
                  </p>
                  <p>
                    <strong>Radius:</strong> {parseFloat(dxfInfo.Radius).toFixed(3)}
                  </p>
                  <p>
                    <strong>Start Angle:</strong> {parseFloat(dxfInfo['Start angle']).toFixed(3)}°
                  </p>
                  <p>
                    <strong>End Angle:</strong> {parseFloat(dxfInfo['End angle']).toFixed(3)}°
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Scans Card */}
          <div className="card custom-card mt-5">
            <div className="card-body">
              <h5 className="card-title">Scans</h5>
              <input
                type="number"
                placeholder="Number of Scans"
                value={numScans}
                onChange={(e) => setNumScans(e.target.value)}
                className="form-control mb-4"
                min="1"
                disabled={loading}
              />
              <button onClick={submitScans} className="btn btn-custom-primary w-100" disabled={loading}>
                Submit Scans ✅
              </button>
              {angles && (
                <div className="angles-box mt-4">
                  <strong>Angles:</strong> {angles}
                </div>
              )}
              {loading && (
                <div className="spinner-border text-primary" role="status">
                  <span className="visually-hidden">Loading...</span>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right Column */}
        <div className="col-lg-6 col-md-12">
          {/* Laser Parameters Card */}
          <div className="card custom-card">
            <div className="card-body">
              <h5 className="card-title">Laser Parameters</h5>
              <button onClick={getLaserParams} className="btn btn-custom-success w-100 mb-4" disabled={loading}>
                Get Parameters 🔍
              </button>
              <div className="params-container">
                {laserParams.length > 0 ? (
                  laserParams.map((p, i) => (
                    <div key={i} className="param-card mt-4">
                      <div className="card-body">
                        <h6 className="card-subtitle mb-2">Point {i + 1}</h6>
                        <p>
                          <strong>Power:</strong> {p.laser_power?.toFixed(2)} W
                        </p>
                        <p>
                          <strong>Speed:</strong> {p.scan_speed?.toFixed(2)} mm/s
                        </p>
                        <p>
                          <strong>Perp. Distance:</strong> {p.perp_dist?.toFixed(2)} mm
                        </p>
                        <p>
                          <strong>Ref. Distance:</strong> {p.RefDist_mm?.toFixed(2)} mm
                        </p>
                        <p>
                          <strong>Scans:</strong> {p.num_scans}
                        </p>
                      </div>
                    </div>
                  ))
                ) : (
                  <p className="text-muted">No parameters yet.</p>
                )}
              </div>
              {loading && (
                <div className="spinner-border text-primary" role="status">
                  <span className="visually-hidden">Loading...</span>
                </div>
              )}
            </div>
          </div>

          {/* G-code Card */}
          <div className="card custom-card mt-5">
            <div className="card-body">
              <h5 className="card-title">G-Code</h5>
              <button onClick={getGcode} className="btn btn-custom-danger w-100 mb-4" disabled={loading}>
                Get GCODE 📄
              </button>
              {gcode && (
                <div className="gcode-container">
                  <pre className="gcode-pre">{gcode}</pre>
                  <button
                    onClick={copyToClipboard}
                    className={`btn btn-copy ${copied ? 'btn-success' : ''}`}
                  >
                    {copied ? 'Copied! ✅' : '📋'}
                  </button>
                </div>
              )}
              {loading && (
                <div className="spinner-border text-primary" role="status">
                  <span className="visually-hidden">Loading...</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Camera Link */}
      <div className="text-center mt-5">
        <a href="/camera" className="btn btn-custom-info btn-lg">
          Camera 🎥
        </a>
      </div>
    </div>
  );
}

export default Home;