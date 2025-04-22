from flask import request, jsonify, Blueprint, current_app
from app import db, mail
from app.models import User, OTP, RPass
from flask_mail import Message
from werkzeug.security import check_password_hash, generate_password_hash
import random
import jwt
from datetime import datetime, timedelta
import os
import numpy as np
import pandas as pd
import cv2
from werkzeug.utils import secure_filename
import cloudinary
import cloudinary.uploader
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import logging
import ezdxf
from collections import deque
import uuid

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

cloudinary.config(
    cloud_name='dl40nkfz8',
    api_key='138355678461881',
    api_secret='7paxIdG1dkZDKdf2xN2TnpKE-7M'
)

ALLOWED_EXTENSIONS = {'dxf'}
GCODE_STORAGE = deque(maxlen=10)

# Load synthetic dataset
csv_path = os.getenv('CSV_PATH', 'synthetic_bend_dataset.csv')
csv_full_path = os.path.join(os.getcwd(), csv_path)
logger.debug("Attempting to load CSV from: %s", csv_full_path)
if not os.path.exists(csv_full_path):
    logger.error("CSV file not found at: %s", csv_full_path)
    raise FileNotFoundError(f"CSV file not found at: {csv_full_path}")

logger.debug("Loading CSV: %s", csv_full_path)
try:
    synthetic_df = pd.read_csv(csv_full_path)
    required_columns = ['InputPower_Watt', 'ScanSpeed', 'PerpDist_mm', 'RefDist_mm', 'Curr_Iter', 'PredictedBend', 'Confidence']
    missing_cols = [col for col in required_columns if col not in synthetic_df.columns]
    if missing_cols:
        logger.error("Missing columns in CSV: %s", missing_cols)
        raise ValueError(f"Missing columns in CSV: {missing_cols}")
    logger.info("CSV loaded successfully. Shape: %s, Columns: %s", synthetic_df.shape, synthetic_df.columns.tolist())
except Exception as e:
    logger.error("Failed to load CSV: %s", str(e))
    raise

# Define prediction features
pred_features = ['InputPower_Watt', 'ScanSpeed', 'PerpDist_mm', 'RefDist_mm', 'Curr_Iter']

def find_best_params(synthetic_df, target_bend, pred_features, top_k=1):
    logger.debug("Finding parameters for target_bend: %s", target_bend)
    synthetic_df['BendDiff'] = np.abs(synthetic_df['PredictedBend'] - target_bend)
    selected = synthetic_df.sort_values(['BendDiff', 'Confidence'], ascending=[True, False]).head(top_k)
    selected['Curr_Iter'] = np.round(selected['Curr_Iter']).astype(int)
    if selected.empty:
        logger.warning("No parameters found for target_bend: %s", target_bend)
    else:
        logger.debug("Selected parameters: %s", selected[pred_features].to_dict())
    return selected[pred_features + ['PredictedBend', 'Confidence']]

def generate_cnc_code(scan_data, start_x=0, start_y=0, start_z=0, rapid_feed=5000):
    """
    Generates Siemens CNC G-code for laser scanning based on input tuples.
    :param scan_data: List of tuples [(x, scan_speed, num_scans, y_shift, z_abs, laser_power), ...]
    :param start_x: Initial X position
    :param start_y: Initial Y position
    :param start_z: Initial Z position (absolute, overwritten by scan_data z_abs)
    :param rapid_feed: Feed rate for rapid movements (laser OFF)
    :return: CNC G-code as a string
    """
    cnc_code = []

    # Initialize program
    cnc_code.append("NC/MPF/WELD_1")
    cnc_code.append("N10 R10-011")
    cnc_code.append("N11 M50 ; AIR VALVE ON")
    cnc_code.append("N12 M54 ; ARGON SHIELDING GAS ON")
    cnc_code.append("N13 STOPRET")
    cnc_code.append("N14 $A_DBB[2]=1 ; PROGRAM START")
    cnc_code.append("N15 STOPRET")

    current_x, current_y = start_x, start_y
    current_z = start_z

    for i, (x, scan_speed, num_scans, y_shift, z_abs, laser_power) in enumerate(scan_data):
        # Add comment with laser power and Z position (perpendicular distance)
        cnc_code.append(f"; Scan {i+1} for Laser Power: {laser_power} W, Z (Perp Dist): {z_abs:.3f} mm")
        
        # Move to Z position before scan (absolute)
        if z_abs != current_z:
            cnc_code.append(f"N16 G01 G90 G54 Z{z_abs:.3f} F{rapid_feed} ; Set Z (Perpendicular Distance)")
            current_z = z_abs

        # Turn on laser before scan
        cnc_code.append("N20 $A_DBB[19]=1 ; LASER ON")
        cnc_code.append("N21 STOPRET")

        for _ in range(num_scans):
            cnc_code.append(f"N30 G01 G91 G54 X{x:.3f} F{scan_speed:.1f} ; Scan forward")
            cnc_code.append("N31 G04 X10 ; WAIT FOR 5 SEC")
            cnc_code.append(f"N32 G01 G91 G54 X{-x:.3f} F{scan_speed:.1f} ; Scan backward")
            cnc_code.append("N33 G04 X10 ; WAIT FOR 5 SEC")

        # Turn off laser after scans
        cnc_code.append("N40 $A_DBB[19]=0 ; LASER OFF")
        cnc_code.append("N41 STOPRET")

        # Move to next Y position (relative), if any
        if y_shift != 0:
            cnc_code.append(f"N50 G01 G91 G54 Y{y_shift:.3f} F{rapid_feed} ; Move Y")
            current_y += y_shift

    # Final shutdown
    cnc_code.append("N60 $A_DBB[2]=0 ; PROGRAM OFF")
    cnc_code.append("N61 STOPRET")
    cnc_code.append("N62 M51 ; AIR VALVE OFF")
    cnc_code.append("N63 M55 ; ARGON SHIELDING GAS OFF")
    cnc_code.append("N64 M30")  # End program

    return "\n".join(cnc_code)

def generate_jwt_token(user):
    payload = {
        'id': user.id,
        'name': user.name,
        'email': user.email,
        'exp': datetime.utcnow() + timedelta(days=7)
    }
    token = jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')
    return token

@auth_bp.route('/')
def index():
    return jsonify({"status": "Welcome to the Flask App!"})

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.json
    existing_user = User.query.filter_by(email=data['email']).first()
    if existing_user:
        return jsonify({"success": False, "message": "User already registered", "existing_user": existing_user.to_dict()}), 401
    msg = Message(
        'OTP for registration to the Laser Bending Application',
        sender='ashwin.aj4545@gmail.com',
        recipients=[data['email']]
    )
    otp = random.randint(1000, 9999)
    msg.html = f"""
    <p>Hey! Welcome to the Laser Bending application.</p>
    <p>Please enter this OTP for registration:</p>
    <p style="font-size: 24px; font-weight: bold; color: blue;">{otp}</p>
    """
    mail.send(msg)
    existing_otp = OTP.query.filter_by(email=data['email']).first()
    if existing_otp:
        existing_otp.otp = otp
    else:
        new_otp = OTP(email=data['email'], otp=otp)
        db.session.add(new_otp)
    db.session.commit()

    hashed_password = generate_password_hash(data['password'], method="pbkdf2:sha256")
    new_user = User(name=data['name'], email=data['email'], password=hashed_password)
    db.session.add(new_user)
    db.session.commit()
    token = generate_jwt_token(new_user)
    return jsonify({"success": True, "message": "User registered successfully", "user": new_user.to_dict(), 'token': token}), 201

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(email=data['email']).first()
    if not user:
        return jsonify({"success": False, "message": "User doesn't exist"})
    if check_password_hash(user.password, data['password']):
        token = generate_jwt_token(user)
        return jsonify({"success": True, "message": "Login successful", "user": user.to_dict(), 'token': token}), 201
    return jsonify({"success": False, "message": "Invalid credentials"}), 401

@auth_bp.route('/forgot-pass', methods=['POST'])
def forgot_pass():
    data = request.json
    user = User.query.filter_by(email=data['email']).first()
    if not user:
        return jsonify({"success": False, "message": "User doesn't exist"}), 401
    msg = Message(
        'Reset Link for password',
        sender='ashwin.aj4545@gmail.com',
        recipients=[data['email']]
    )
    otp = random.randint(1000, 9999)
    msg.html = f"""
    <p>Please enter this OTP to reset password:</p>
    <p style="font-size: 24px; font-weight: bold; color: blue;">{otp}</p>
    """
    mail.send(msg)
    existing_otp = RPass.query.filter_by(email=data['email']).first()
    if existing_otp:
        existing_otp.otp = otp
    else:
        new_otp = RPass(email=data['email'], otp=otp)
        db.session.add(new_otp)
    db.session.commit()
    return jsonify({"success": True, "message": "OTP sent successfully"}), 201

@auth_bp.route('/verify-r-otp', methods=['POST'])
def verifyROtp():
    data = request.json
    user1 = OTP.query.filter_by(email=data['email']).first()
    if not user1:
        return jsonify({"success": False, "message": "Send OTP again"}), 401
    if data['otp'] == user1.otp:
        db.session.delete(user1)
        db.session.commit()
        return jsonify({"success": True, "message": "OTP verified successfully"}), 201
    otp = random.randint(1000, 9999)
    msg = Message(
        'OTP for registration to the Laser Bending Application',
        sender='ashwin.aj4545@gmail.com',
        recipients=[data['email']]
    )
    msg.html = f"""
    <p>Hey! Welcome to the Laser Bending application.</p>
    <p>Please enter this OTP for registration:</p>
    <p style="font-size: 24px; font-weight: bold; color: blue;">{otp}</p>
    """
    mail.send(msg)
    existing_otp = OTP.query.filter_by(email=data['email']).first()
    if existing_otp:
        existing_otp.otp = otp
    else:
        new_otp = OTP(email=data['email'], otp=otp)
        db.session.add(new_otp)
    db.session.commit()
    return jsonify({"success": False, "message": "Wrong OTP! Sent again."}), 401

@auth_bp.route('/verify-f-otp', methods=['POST'])
def verifyFOtp():
    data = request.json
    user1 = RPass.query.filter_by(email=data['email']).first()
    if not user1:
        return jsonify({"success": False, "message": "Send OTP again"}), 401
    if data['otp'] == user1.otp:
        db.session.delete(user1)
        db.session.commit()
        return jsonify({"success": True, "message": "OTP verified successfully"}), 201
    otp = random.randint(1000, 9999)
    msg = Message(
        'Reset Link for password',
        sender='ashwin.aj4545@gmail.com',
        recipients=[data['email']]
    )
    msg.html = f"""
    <p>Please enter this OTP to reset password:</p>
    <p style="font-size: 24px; font-weight: bold; color: blue;">{otp}</p>
    """
    mail.send(msg)
    existing_otp = RPass.query.filter_by(email=data['email']).first()
    if existing_otp:
        existing_otp.otp = otp
    else:
        new_otp = RPass(email=data['email'], otp=otp)
        db.session.add(new_otp)
    db.session.commit()
    return jsonify({"success": False, "message": "Wrong OTP! Sent again."}), 401

@auth_bp.route('/reset-pass/<string:email>', methods=['POST'])
def resetPass(email):
    data = request.json
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 401
    hashedPass = generate_password_hash(data['password'], method="pbkdf2:sha256")
    user.password = hashedPass
    db.session.commit()
    return jsonify({"success": True, "message": "Password changed successfully"}), 201

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_dxf(file_path):
    doc = ezdxf.readfile(file_path)
    msp = doc.modelspace()
    for entity in msp:
        if entity.dxftype() == 'ARC':
            center = entity.dxf.center
            radius = entity.dxf.radius
            start_angle = entity.dxf.start_angle
            end_angle = entity.dxf.end_angle
            return {"Center": [center.x, center.y, center.z], "Radius": radius, "Start angle": start_angle, "End angle": end_angle}

@auth_bp.route('/handle-dxf', methods=['POST'])
def handleDxf():
    if not os.path.exists(current_app.config['UPLOAD_FOLDER']):
        os.makedirs(current_app.config['UPLOAD_FOLDER'])
    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "message": "No file selected"}), 400
    if file and allowed_file(file.filename):
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file.filename)
        file.save(file_path)
    try:
        dxf_info = process_dxf(file_path)
        return jsonify({"success": True, "message": "File uploaded successfully", "dxf_info": dxf_info}), 200
    except Exception as e:
        return jsonify({"success": False, "message": f"Error processing DXF file: {str(e)}"}), 500

@auth_bp.route('/handle-angle', methods=['POST'])
def handleAngle():
    data = request.json
    x_center = data['x']
    y_center = data['y']
    radius = data['radius']
    start_angle = np.deg2rad(data['start_angle'])
    end_angle = np.deg2rad(data['end_angle'])
    num_points = data['num_points']
    angles = np.linspace(start_angle, end_angle, num_points)
    x = x_center + radius * np.cos(angles)
    y = y_center + radius * np.sin(angles)
    line_angles = []
    adjusted_angles = []
    for i in range(len(x) - 1):
        dx = x[i + 1] - x[i]
        dy = y[i + 1] - y[i]
        angle = np.arctan2(dy, dx)
        line_angles.append(np.rad2deg(angle))
        adjusted_angle = 180 - np.rad2deg(angle)
        adjusted_angles.append(adjusted_angle)
    return jsonify({"success": True, "message": "Angles found out", "angles": adjusted_angles})

@auth_bp.route('/predict', methods=['POST'])
def predict():
    try:
        data = request.get_json()
        logger.debug("Received request: %s", data)
        if not data or 'angles' not in data:
            logger.warning("Missing angles in request")
            return jsonify({'error': 'Missing angles in request'}), 400

        angles = data['angles']
        if not isinstance(angles, list):
            logger.warning("angles must be a list")
            return jsonify({'error': 'angles must be a list'}), 400

        response = []
        for angle in angles:
            try:
                target_bend = float(angle)
                result = find_best_params(synthetic_df, target_bend, pred_features, top_k=1)
                
                if result.empty:
                    logger.warning("No parameters found for target_bend: %s", target_bend)
                    response.append({
                        'angle': target_bend,
                        'error': 'No parameters found for this angle'
                    })
                    continue
                
                result_dict = result.iloc[0].to_dict()
                
                prediction = {
                    'angle': target_bend,
                    'laser_power': result_dict['InputPower_Watt'],
                    'scan_speed': result_dict['ScanSpeed'],
                    'perp_dist': result_dict['PerpDist_mm'],
                    'num_scans': int(result_dict['Curr_Iter']),
                    'RefDist_mm': result_dict['RefDist_mm']
                }
                response.append(prediction)
                logger.debug("Prediction for angle %s: %s", target_bend, prediction)
            
            except ValueError:
                logger.warning("Invalid angle value: %s", angle)
                response.append({
                    'angle': angle,
                    'error': 'Invalid angle value'
                })
        
        if not response:
            logger.warning("No valid predictions generated")
            return jsonify({'error': 'No valid predictions generated'}), 404
        
        logger.info("Response sent: %s", response)
        return jsonify(response), 200
    
    except Exception as e:
        logger.error("Server error: %s", str(e))
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@auth_bp.route('/generate-gcode', methods=['POST'])
def generate_gcode():
    try:
        data = request.get_json()
        logger.debug("Received G-code request: %s", data)
        if not data or 'angles' not in data:
            logger.warning("Missing angles in request")
            return jsonify({'error': 'Missing angles in request'}), 400

        angles = data['angles']
        if not isinstance(angles, list):
            logger.warning("angles must be a list")
            return jsonify({'error': 'angles must be a list'}), 400

        # Generate predictions internally (same logic as /predict)
        predictions = []
        scan_data = []
        for angle in angles:
            try:
                target_bend = float(angle)
                result = find_best_params(synthetic_df, target_bend, pred_features, top_k=1)
                
                if result.empty:
                    logger.warning("No parameters found for target_bend: %s", target_bend)
                    predictions.append({
                        'angle': target_bend,
                        'error': 'No parameters found for this angle'
                    })
                    continue
                
                result_dict = result.iloc[0].to_dict()
                
                prediction = {
                    'angle': target_bend,
                    'laser_power': result_dict['InputPower_Watt'],
                    'scan_speed': result_dict['ScanSpeed'],
                    'perp_dist': result_dict['PerpDist_mm'],
                    'num_scans': int(result_dict['Curr_Iter']),
                    'RefDist_mm': result_dict['RefDist_mm']
                }
                predictions.append(prediction)
                logger.debug("Prediction for angle %s: %s", target_bend, prediction)
                
                # Prepare tuple for G-code: (x, scan_speed, num_scans, y_shift, z_abs, laser_power)
                scan_tuple = (
                    result_dict['RefDist_mm'],      # x
                    result_dict['ScanSpeed'],       # scan_speed
                    int(result_dict['Curr_Iter']),  # num_scans
                    0.0,                            # y_shift (no Y movement)
                    result_dict['PerpDist_mm'],     # z_abs (perpendicular distance)
                    result_dict['InputPower_Watt']  # laser_power
                )
                scan_data.append(scan_tuple)
            
            except ValueError:
                logger.warning("Invalid angle value: %s", angle)
                predictions.append({
                    'angle': angle,
                    'error': 'Invalid angle value'
                })
        
        if not scan_data:
            logger.warning("No valid predictions generated for G-code")
            return jsonify({'error': 'No valid predictions generated'}), 404
        
        # Generate G-code
        try:
            gcode = generate_cnc_code(scan_data)
            logger.debug("Generated G-code:\n%s", gcode)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            gcode_filename = f"laser_bending_{timestamp}.gcode"
            request_id = str(uuid.uuid4())  # Unique ID for this GCode
            gcode_entry = {
                'filename': gcode_filename,
                'gcode': gcode,
                'timestamp': timestamp,
                'predictions': predictions,
                'request_id': request_id
            }
            GCODE_STORAGE.append(gcode_entry)
            logger.info("Stored GCode in memory: %s (ID: %s)", gcode_filename, request_id)

        except Exception as e:
            logger.error("Failed to generate G-code: %s", str(e))
            return jsonify({'error': f'G-code generation failed: {str(e)}'}), 500


        # Return predictions and G-code
        response_dict = {
            'predictions': predictions,
            'gcode': gcode,
            'filename': gcode_filename,
            'request_id': request_id
        }
        
        logger.info("G-code response sent: %s", response_dict)
        return jsonify(response_dict), 200
    
    except Exception as e:
        logger.error("Server error: %s", str(e))
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@auth_bp.route('/latest-gcode', methods=['GET'])
def latest_gcode():
    try:
        if not GCODE_STORAGE:
            logger.warning("No GCode available")
            return jsonify({'error': 'No GCode available'}), 404
        latest_entry = GCODE_STORAGE[-1]  # Get most recent
        response_dict = {
            'filename': latest_entry['filename'],
            'gcode': latest_entry['gcode'],
            'timestamp': latest_entry['timestamp'],
            'predictions': latest_entry['predictions'],
            'request_id': latest_entry['request_id']
        }
        logger.info("Sent latest GCode: %s (ID: %s)", latest_entry['filename'], latest_entry['request_id'])
        return jsonify(response_dict), 200
    except Exception as e:
        logger.error("Failed to fetch latest GCode: %s", str(e))
        return jsonify({'error': f'Failed to fetch GCode: {str(e)}'}), 500

@auth_bp.route('/confirm-gcode/<request_id>', methods=['POST'])
def confirm_gcode(request_id):
    try:
        for i, entry in enumerate(GCODE_STORAGE):
            if entry['request_id'] == request_id:
                GCODE_STORAGE.remove(entry)
                logger.info("Deleted GCode from storage: %s (ID: %s)", entry['filename'], request_id)
                return jsonify({'message': f'GCode {request_id} deleted'}), 200
        logger.warning("GCode not found: %s", request_id)
        return jsonify({'error': f'GCode {request_id} not found'}), 404
    except Exception as e:
        logger.error("Failed to confirm GCode: %s", str(e))
        return jsonify({'error': f'Failed to confirm: {str(e)}'}), 500
    

@auth_bp.route('/graph', methods=['POST'])
def generate_arc_plot():
    data = request.json
    center_x, center_y = data['x'], data['y']
    radius = data['radius']
    start_angle = data['start_angle']
    end_angle = data['end_angle']
    start_angle_rad = np.radians(start_angle)
    end_angle_rad = np.radians(end_angle)
    theta = np.linspace(start_angle_rad, end_angle_rad, 100)
    x_points = center_x + radius * np.cos(theta)
    y_points = center_y + radius * np.sin(theta)
    y_points_mirrored = -y_points
    plt.plot(x_points, y_points, label="Original ARC", color="blue")
    plt.plot(x_points, y_points_mirrored, label="Mirrored ARC", color="orange", linestyle="dashed")
    plt.scatter([center_x], [center_y], color='red', label="Center")
    for i in range(len(x_points) - 1):
        plt.plot([x_points[i], x_points[i + 1]], [y_points_mirrored[i], y_points_mirrored[i + 1]], 
                 color="green", linestyle="--", linewidth=0.8)
    plt.axis('equal')
    plt.title('Original and Mirrored ARC')
    plt.xlabel('X')
    plt.ylabel('Y')
    plt.legend()
    plt.grid(True)
    img_io = io.BytesIO()
    plt.savefig(img_io, format='png')
    img_io.seek(0)
    plt.close()
    response = cloudinary.uploader.upload(img_io, folder="arc_images")
    return jsonify({"image_url": response["secure_url"]})

@auth_bp.route('/angle-graph', methods=['POST'])
def generate_arc_angle_plot():
    data = request.json
    x_center = data['x']
    y_center = data['y']
    radius = data['radius']
    start_angle = np.deg2rad(data['start_angle'])
    end_angle = np.deg2rad(data['end_angle'])
    num_points = data['num_points']
    angles = np.linspace(start_angle, end_angle, num_points)
    x = x_center + radius * np.cos(angles)
    y = -(y_center + radius * np.sin(angles))
    line_angles = []
    adjusted_angles = []
    for i in range(len(x) - 1):
        dx = x[i + 1] - x[i]
        dy = y[i + 1] - y[i]
        angle = np.arctan2(dy, dx)
        line_angles.append(np.rad2deg(angle))
        adjusted_angle = 180 - np.rad2deg(angle)
        adjusted_angles.append(adjusted_angle)
    plt.figure(figsize=(12, 8))
    plt.plot(x, y, label="Mirrored ARC with Tangent Angles", color="blue")
    plt.scatter(x, y, color="orange", label="Points on Mirrored ARC")
    plt.scatter([x_center], [-y_center], color="red", label="Center (Mirrored)")
    for i in range(len(x) - 1):
        plt.plot([x[i], x[i + 1]], [y[i], y[i + 1]], color="purple", linestyle="-", label=f"Line {i + 1}" if i == 0 else "")
    theta = np.linspace(start_angle, end_angle, 100)
    x_points = x_center + radius * np.cos(theta)
    y_points = -(y_center + radius * np.sin(theta))
    plt.plot(x_points, y_points, label="Original ARC (Mirrored)", color="green", linestyle="-")
    plt.axis("equal")
    plt.xlabel("X")
    plt.ylabel("Y")
    plt.title("Combined Plot: Original ARC and Mirrored ARC with Tangent Lines")
    plt.legend()
    plt.grid(True)
    img_io = io.BytesIO()
    plt.savefig(img_io, format='png')
    img_io.seek(0)
    plt.close()
    response = cloudinary.uploader.upload(img_io, folder="arc_images")
    return jsonify({"image_url": response["secure_url"]})

@auth_bp.route('/save-snapshot', methods=['POST'])
def save_snapshot():
    snapshot = request.files['snapshot']
    coordinates = request.form['coordinates']
    expected_angle = request.form.get('expectedAngle', '')
    coords = eval(coordinates)
    logger.debug("Coordinates: %s, Expected Angle: %s", coords, expected_angle)

    # Save snapshot temporarily to UPLOAD_FOLDER
    if not os.path.exists(current_app.config['UPLOAD_FOLDER']):
        os.makedirs(current_app.config['UPLOAD_FOLDER'])
    filename = secure_filename(snapshot.filename)
    snapshot_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    snapshot.save(snapshot_path)

    # Upload snapshot to Cloudinary
    try:
        logger.debug("Uploading snapshot to Cloudinary: %s", snapshot_path)
        response = cloudinary.uploader.upload(
            snapshot_path,
            folder="snapshots",  # Specify a folder in Cloudinary (e.g., "snapshots")
            public_id=filename.rsplit('.', 1)[0],  # Use filename without extension as public_id
            overwrite=True  # Overwrite if the file exists
        )
        cloudinary_url = response["secure_url"]  # Get the secure URL of the uploaded image
        print(cloudinary_url)
        logger.info("Snapshot uploaded to Cloudinary: %s", cloudinary_url)
    except Exception as e:
        logger.error("Failed to upload snapshot to Cloudinary: %s", str(e))
        return jsonify({'success': False, 'message': f'Failed to upload snapshot to Cloudinary: {str(e)}'}), 500

    # Process the image (existing logic)
    image = cv2.imread(snapshot_path)
    if image is None:
        logger.error("Failed to load snapshot: %s", snapshot_path)
        return jsonify({'success': False, 'warning': 'Failed to load snapshot'}), 500

    bbox = detect_metal_sheet(image)
    if bbox:
        x, y, w, h = bbox
        roi = image[y:y+h, x:x+w]
    else:
        roi = image

    wire_contour = detect_wire_contour(roi)
    if wire_contour is None:
        logger.warning("No wire contour detected")
        return jsonify({'success': False, 'warning': 'No wire contour detected'}), 500

    mask = np.zeros_like(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY))
    cv2.drawContours(mask, [wire_contour], -1, 255, thickness=cv2.FILLED)
    bend_points, angles_dict = detect_bends_and_angles(
        mask, roi, horizontal_only=True, RIGHT_ROI=0, minSegmentLength=40, minBendSpacing=50
    )

    if not bend_points:
        logger.warning("No bend points detected")
        return jsonify({'success': False, 'warning': 'No bend points detected'}), 500

    laser_x, laser_y = coords.get('x', 0), coords.get('y', 0)
    closest_idx = min(range(len(bend_points)), key=lambda i: np.hypot(bend_points[i][0] - laser_x, bend_points[i][1] - laser_y))
    closest_bend = bend_points[closest_idx]
    detected_angle = angles_dict.get(f"Bend {closest_idx + 1}", 0)

    warning = None
    if expected_angle:
        expected_angle = float(expected_angle)
        normalized_angle = abs(detected_angle % 180)
        if normalized_angle > 90:
            normalized_angle = 180 - normalized_angle
        angle_diff = abs(normalized_angle - expected_angle)
        threshold = 1.0
        logger.debug("Angle comparison: detected=%.2f, expected=%.2f, diff=%.2f", normalized_angle, expected_angle, angle_diff)
        if angle_diff > threshold:
            warning = f'Angle deviation too high: detected {normalized_angle:.2f}° vs expected {expected_angle:.2f}°'
    else:
        warning = 'No expected angle provided'

    closest_bend_serializable = [int(closest_bend[0]), int(closest_bend[1])]
    response = {
        'success': True,
        'detected_angle': float(detected_angle),
        'closest_bend': closest_bend_serializable,
        'cloudinary_url': cloudinary_url  # Add the Cloudinary URL to the response
    }
    if warning:
        response['warning'] = warning

    logger.info("Snapshot response: %s", response)
    return jsonify(response), 200

def detect_metal_sheet(image, min_area=5000, min_aspect_ratio=0.5, max_aspect_ratio=3.0):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    valid_contours = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        aspect_ratio = w / float(h)
        if min_aspect_ratio <= aspect_ratio <= max_aspect_ratio:
            approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
            if len(approx) == 4:
                valid_contours.append((contour, (x, y, w, h)))
    if not valid_contours:
        return None
    _, bounding_box = max(valid_contours, key=lambda c: cv2.contourArea(c[0]))
    return bounding_box

def detect_wire_contour(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    wire_contour = max(contours, key=lambda cnt: cv2.arcLength(cnt, closed=True))
    return wire_contour

def detect_bends_and_angles(mask, image, horizontal_only=False, RIGHT_ROI=0, minSegmentLength=30, minBendSpacing=20):
    edges = cv2.Canny(mask, 50, 150)
    dilated_edges = cv2.dilate(edges, np.ones((3,3), np.uint8))
    lines = cv2.HoughLinesP(edges, rho=1, theta=np.pi/180, threshold=50, minLineLength=30, maxLineGap=10)
    if lines is None:
        return [], {}
    segments = [(x1, y1, x2, y2) for line in lines for x1, y1, x2, y2 in line]
    segments = [seg for seg in segments if np.hypot(seg[2] - seg[0], seg[3] - seg[1]) > minSegmentLength]
    segments.sort(key=lambda seg: seg[0])
    img_width = image.shape[1]
    right_roi_threshold = RIGHT_ROI * img_width
    bend_points = []
    angles_dict = {}
    for i in range(len(segments) - 1):
        x1, y1, x2, y2 = segments[i]
        x1_next, y1_next, x2_next, y2_next = segments[i + 1]
        angle1 = np.arctan2(y2 - y1, x2 - x1)
        angle2 = np.arctan2(y2_next - y1_next, x2_next - x1_next)
        angle_diff = abs(angle1 - angle2) * 180 / np.pi
        if horizontal_only and x1 < right_roi_threshold:
            continue
        if bend_points and np.hypot(x1 - bend_points[-1][0], y1 - bend_points[-1][1]) < minBendSpacing:
            continue
        bend_points.append((x1, y1))
        angles_dict[f"Bend {len(bend_points)}"] = round(angle_diff, 2)
    return bend_points, angles_dict

