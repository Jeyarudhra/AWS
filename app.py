from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import requests
from ldap3 import Connection, Server, ALL, SUBTREE
import base64
from PIL import Image, ImageDraw, ImageFont
import io
from pymongo import MongoClient
from bson.objectid import ObjectId
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key'
LDAP_SERVER = "ldap://10.30.1.50"
SEARCH_BASE = 'DC=sandhata,DC=local'
HR_GROUP_DN = "CN=HR,CN=Users,DC=sandhata,DC=local"
ATTRIBUTES = ['cn', 'sn', 'givenName', 'mail', 'telephoneNumber', 'description', 'department', 'manager', 'directReports', 'company']


CLIENT_ID = 'd0e3d90d-ff2c-416f-8e43-4f9df6bb7cb0'
CLIENT_SECRET = 'D.E8Q~AEN8Av2IuoirALVFW9M_SEMf-3z6ag-bcP'
REDIRECT_URI = 'http://localhost:5000/callback'
RESOURCE = 'https://graph.microsoft.com/'
AUTHORITY_URL = 'https://login.microsoftonline.com/common'
TENANT_ID = '5e45e2ef-d6aa-4ad1-aaca-a7187394a753'
 
def get_access_token():
    token_url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    token_data = {
        'grant_type': 'client_credentials',
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'scope': 'https://graph.microsoft.com/.default'
    }
    token_response = requests.post(token_url, data=token_data)
    token_response.raise_for_status()
    return token_response.json()['access_token']
 
def create_logo(first_name, last_name):
    logo_size = (100, 100)
    background_color = (255, 255, 255)
    logo = Image.new("RGB", logo_size, background_color)
 
    draw = ImageDraw.Draw(logo)
    font_size = 30
    font = ImageFont.truetype("arial.ttf", font_size)
 
    text = f"{first_name[0].upper()}{last_name[0].upper()}"
    text_width, text_height = draw.textbbox((0, 0), text, font=font)[2:]
 
    position = ((logo_size[0] - text_width) / 2, (logo_size[1] - text_height) / 2)
    draw.text(position, text, fill=(0, 0, 0), font=font)
 
    return logo
 
def get_user_profile(access_token, user_id):
    user_profile_url = f"https://graph.microsoft.com/v1.0/users/{user_id}"
    headers = {'Authorization': 'Bearer ' + access_token}
    response = requests.get(user_profile_url, headers=headers)
    if response.status_code == 200:
        user_profile = response.json()
        user_profile.pop('photo', None)  # Remove photo from profile for now
        return user_profile
    else:
        print(f"Error fetching user profile: {response.status_code} - {response.text}")
        return None
 
def get_user_photo(access_token, user_id):
    user_photo_url = f"https://graph.microsoft.com/v1.0/users/{user_id}/photo/$value"
    headers = {'Authorization': 'Bearer ' + access_token}
    response = requests.get(user_photo_url, headers=headers, stream=True)
    if response.status_code == 200:
        photo_data = response.content
        return photo_data
    else:
        print(f"Error fetching user photo: {response.status_code} - {response.text}")
        return None
 
 
 
def get_cn_names():
    email = session['user']
    password = session['password']
 
    server = Server(LDAP_SERVER, get_info=ALL)
    try:
        con = Connection(server, user=email, password=password, auto_bind=True)
        con.search(SEARCH_BASE, '(objectClass=user)', attributes=['cn'])
        cn_names = [entry.cn.value for entry in con.entries]
        con.unbind()
        return cn_names
    except Exception as e:
        print(f"Failed to retrieve CN names: {e}")
        return []
    

def is_hr_member(email, password):
    server = Server(LDAP_SERVER, get_info=ALL)
    con = Connection(server, user=email, password=password)
 
    if not con.bind():
        return False, 'Invalid credentials', None
 
    # Fetch user's CN
    search_filter = f"(mail={email})"
    con.search(SEARCH_BASE, search_filter, attributes=['cn'])
    if con.entries:
        user_cn = con.entries[0].cn.value
    else:
        con.unbind()
        return False, 'Invalid credentials', None
 
   
    con.search(HR_GROUP_DN, "(objectClass=group)", attributes=['member'])
    hr_emails = []
    for entry in con.entries:
        if 'member' in entry:
            members = entry.member.values
            for member_dn in members:
                con.search(member_dn, "(objectClass=person)", attributes=['mail'])
                if con.entries:
                    member_email = con.entries[0].mail.value
                    hr_emails.append(member_email)
 
    is_hr = email in hr_emails
    con.unbind()
   
    return is_hr, None, user_cn if is_hr else user_cn
 
@app.route('/', methods=['GET', 'POST'])
def index():
    error = None
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
 
        if email and password:
            is_hr, error, user_cn = is_hr_member(email, password)
            if error:
                return render_template('index.html', error=error)
            session['user'] = email
            session['password'] = password  # Store the password for future LDAP queries
            session['is_hr'] = is_hr
            session['cn'] = user_cn
            return render_template('intranet.html',cn=session['cn']) 
        else:
            error = 'Invalid credentials'
    return render_template('index.html', error=error)

@app.route('/fetch_user_details', methods=['GET'])
def fetch_user_details():
    user_name = request.args.get('user')
    if not user_name:
        return jsonify({"error": "No user specified"}), 400

    try:
        email = session.get('user')
        password = session.get('password')

        if not email or not password:
            return jsonify({"error": "Unauthorized"}), 401

        server = Server(LDAP_SERVER, get_info=ALL)
        con = Connection(server, user=email, password=password, auto_bind=True)

        # Fetch user info
        user_filter = f'(cn={user_name})'
        con.search(SEARCH_BASE, user_filter, attributes=['cn', 'mail', 'telephoneNumber', 'description', 'manager'])
        if not con.entries:
            con.unbind()
            return jsonify({"error": "User not found"}), 404

        user_entry = con.entries[0]
        user_info = {
            'cn': user_entry.cn.value,
            'mail': user_entry.mail.value if 'mail' in user_entry else '',
            'telephoneNumber': user_entry.telephoneNumber.value if 'telephoneNumber' in user_entry else '',
            'description': user_entry.description.value if 'description' in user_entry else '',
        }

        # Fetch manager info
        manager_dn = user_entry.manager.value if 'manager' in user_entry else None
        manager_info = {}
        manager_photo = ''  # Assuming you have a way to fetch manager's photo
        if manager_dn:
            con.search(SEARCH_BASE, f'(distinguishedName={manager_dn})', attributes=['cn', 'mail', 'telephoneNumber', 'description'])
            if con.entries:
                manager_entry = con.entries[0]
                manager_info = {
                    'cn': manager_entry.cn.value,
                    'mail': manager_entry.mail.value if 'mail' in manager_entry else '',
                    'telephoneNumber': manager_entry.telephoneNumber.value if 'telephoneNumber' in manager_entry else '',
                    'description': manager_entry.description.value if 'description' in manager_entry else '',
                }

        # Fetch direct reports
        direct_reports = []
        con.search(SEARCH_BASE, f'(manager=*)', attributes=['cn', 'manager'])
        for entry in con.entries:
            if 'manager' in entry and entry.manager.value == user_entry.entry_dn:
                direct_reports.append({
                    'cn': entry.cn.value,
                    'mail': entry.mail.value if 'mail' in entry else '',
                    'telephoneNumber': entry.telephoneNumber.value if 'telephoneNumber' in entry else '',
                    'description': entry.description.value if 'description' in entry else '',
                })

        con.unbind()

        # Assuming you have a way to fetch photos, otherwise, you can set placeholder images
        # For example:
        user_photo = 'placeholder_base64_user_photo'
        manager_photo = 'placeholder_base64_manager_photo'

        response = {
            'user_info': user_info,
            'manager_info': manager_info,
            'direct_reports': direct_reports,
            'user_photo': user_photo,
            'manager_photo': manager_photo
        }

        return jsonify(response)

    except Exception as e:
        print(f"Error fetching user details: {e}")
        return jsonify({"error": "Failed to fetch user details"}), 500

    
@app.route('/live_search', methods=['GET'])
def live_search():
    term = request.args.get('term')
    if not term:
        return jsonify({"suggestions": []})

    try:
        email = session['user']
        password = session['password']

        server = Server(LDAP_SERVER, get_info=ALL)
        con = Connection(server, user=email, password=password, auto_bind=True)
        search_filter = f'(cn={term}*)'
        con.search(SEARCH_BASE, search_filter, attributes=['cn'])
        suggestions = [entry.cn.value for entry in con.entries]
        con.unbind()

        return jsonify({"suggestions": suggestions})

    except Exception as e:
        print(f"Error in live search: {e}")
        return jsonify({"error": "LDAP search failed"}), 500

if __name__ == '__main__':
    app.run(debug=True)