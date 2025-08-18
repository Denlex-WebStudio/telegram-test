import os
import json
from datetime import datetime
from typing import List, Dict, Any, Set

import gspread
from google.oauth2.service_account import Credentials


APPOINTMENTS_SHEET = 'Записи на прием'
REVIEWS_SHEET = 'Отзывы'
CONSULTATIONS_SHEET = 'Онлайн консультации'
SUBSCRIBERS_SHEET = 'Подписчики'


class SheetsManager:
    def __init__(self, spreadsheet_id: str | None = None):
        self.spreadsheet_id = spreadsheet_id or os.getenv('GOOGLE_SHEETS_ID')
        if not self.spreadsheet_id:
            raise RuntimeError('GOOGLE_SHEETS_ID is not set')

        self.client = self._authorize_client()
        self.spreadsheet = self.client.open_by_key(self.spreadsheet_id)

        self._ensure_sheets()

    # ===== Authorization =====
    def _authorize_client(self):
        json_text = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        if json_text:
            info = json.loads(json_text)
            creds = Credentials.from_service_account_info(info, scopes=scopes)
            return gspread.authorize(creds)
        # fallback to file path
        cred_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
        if cred_path:
            creds = Credentials.from_service_account_file(cred_path, scopes=scopes)
            return gspread.authorize(creds)
        raise RuntimeError('Google credentials are not configured. Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_APPLICATION_CREDENTIALS')

    # ===== Setup helpers =====
    def _ensure_sheet_with_headers(self, title: str, headers: List[str]):
        try:
            ws = self.spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet(title=title, rows=1000, cols=max(10, len(headers)))
        values = ws.get_values('1:1')
        if not values or values[0][:len(headers)] != headers:
            ws.clear()
            ws.update('A1', [headers])
        return ws

    def _ensure_sheets(self):
        self.appointments_headers = [
            'Дата записи', 'Время', 'ФИО пациента', 'Телефон',
            'Врач', 'Специализация', 'Статус', 'ID пользователя', 'Дата создания'
        ]
        self.reviews_headers = [
            'Дата', 'ФИО', 'Оценка', 'Отзыв', 'ID пользователя', 'Статус'
        ]
        self.consultations_headers = [
            'Дата', 'Вопрос', 'ID пользователя', 'Статус', 'Ответ'
        ]
        self.subscribers_headers = [
            'ID пользователя', 'Имя', 'Дата подписки'
        ]

        self.ws_appts = self._ensure_sheet_with_headers(APPOINTMENTS_SHEET, self.appointments_headers)
        self.ws_reviews = self._ensure_sheet_with_headers(REVIEWS_SHEET, self.reviews_headers)
        self.ws_consults = self._ensure_sheet_with_headers(CONSULTATIONS_SHEET, self.consultations_headers)
        self.ws_subs = self._ensure_sheet_with_headers(SUBSCRIBERS_SHEET, self.subscribers_headers)

    # ===== Utilities =====
    @staticmethod
    def _now_str():
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def _to_str(value: Any) -> str:
        return '' if value is None else str(value)

    # ===== Public API (ExcelManager-compatible) =====
    def flush_pending_ops(self):
        return False

    # ---- Appointments ----
    def add_appointment(self, date, time, patient_name, phone, doctor, specialization, user_id):
        rows = self.ws_appts.get_all_values()
        body = rows[1:] if len(rows) > 1 else []
        new_row = [self._to_str(date), self._to_str(time), self._to_str(patient_name), self._to_str(phone),
                   self._to_str(doctor), self._to_str(specialization), 'Новая', self._to_str(user_id), self._now_str()]
        body.append(new_row)
        # Deduplicate by user/date/time/doctor keeping the last by created_at
        col_idx = {h: i for i, h in enumerate(self.appointments_headers)}
        body.sort(key=lambda r: r[col_idx['Дата создания']])
        seen: Set[tuple] = set()
        dedup: List[List[str]] = []
        for r in body:
            key = (r[col_idx['ID пользователя']], r[col_idx['Дата записи']], r[col_idx['Время']], r[col_idx['Врач']])
            if key in seen:
                # replace existing with latest
                for j, dr in enumerate(dedup):
                    dkey = (dr[col_idx['ID пользователя']], dr[col_idx['Дата записи']], dr[col_idx['Время']], dr[col_idx['Врач']])
                    if dkey == key:
                        dedup[j] = r
                        break
            else:
                seen.add(key)
                dedup.append(r)
        self.ws_appts.clear()
        self.ws_appts.update('A1', [self.appointments_headers] + dedup)
        return True

    def get_appointments(self):
        rows = self.ws_appts.get_all_values()
        return rows[1:] if len(rows) > 1 else []

    def get_appointments_by_user(self, user_id):
        uid = self._to_str(user_id)
        all_rows = self.get_appointments()
        result = [r for r in all_rows if self._to_str(r[7]) == uid]
        # Dedup keep last by created_at
        col_idx = {h: i for i, h in enumerate(self.appointments_headers)}
        result.sort(key=lambda r: r[col_idx['Дата создания']])
        dedup_map: Dict[tuple, List[str]] = {}
        for r in result:
            key = (r[col_idx['Дата записи']], r[col_idx['Время']], r[col_idx['Врач']])
            dedup_map[key] = r
        return list(dedup_map.values())

    def get_booked_times(self, doctor_name, date):
        all_rows = self.get_appointments()
        booked = set()
        for r in all_rows:
            status = (r[6] or '').strip().lower()
            if status in ['отменена', 'отменён', 'cancelled', 'canceled']:
                continue
            if self._to_str(r[4]) == self._to_str(doctor_name) and self._to_str(r[0]) == self._to_str(date):
                booked.add(self._to_str(r[1]))
        return booked

    def delete_appointment(self, user_id, date, time, doctor, created_at):
        all_rows = self.get_appointments()
        before = len(all_rows)
        def norm(v):
            return self._to_str(v)
        filtered = [r for r in all_rows if not (
            norm(r[7]) == norm(user_id) and
            norm(r[0]) == norm(date) and
            norm(r[1]) == norm(time) and
            norm(r[4]) == norm(doctor) and
            norm(r[8]) == norm(created_at)
        )]
        if len(filtered) == before:
            return False
        self.ws_appts.clear()
        self.ws_appts.update('A1', [self.appointments_headers] + filtered)
        return True

    def update_appointment_status(self, row_index, new_status):
        # row_index is 1-based including header in ExcelManager; here emulate: header at row 1
        try:
            self.ws_appts.update_cell(row_index, 7, self._to_str(new_status))
            return True
        except Exception:
            return False

    # ---- Reviews ----
    def add_review(self, patient_name, rating, review_text, user_id):
        body = [self._now_str(), self._to_str(patient_name), self._to_str(rating), self._to_str(review_text), self._to_str(user_id), 'Новый']
        self.ws_reviews.append_row(body, value_input_option='USER_ENTERED')
        return True

    def get_reviews(self):
        rows = self.ws_reviews.get_all_values()
        return rows[1:] if len(rows) > 1 else []

    def update_review_status(self, row_index, new_status):
        try:
            self.ws_reviews.update_cell(row_index, 6, self._to_str(new_status))
            return True
        except Exception:
            return False

    # ---- Consultations ----
    def add_consultation(self, question, user_id):
        body = [self._now_str(), self._to_str(question), self._to_str(user_id), 'Новая', '']
        self.ws_consults.append_row(body, value_input_option='USER_ENTERED')
        return True

    def get_consultations(self):
        rows = self.ws_consults.get_all_values()
        return rows[1:] if len(rows) > 1 else []

    # ---- Subscribers ----
    def add_subscriber(self, user_id, user_name):
        uid = self._to_str(user_id)
        rows = self.ws_subs.get_all_values()
        body = rows[1:] if len(rows) > 1 else []
        for r in body:
            if self._to_str(r[0]) == uid:
                return True
        self.ws_subs.append_row([uid, self._to_str(user_name), self._now_str()], value_input_option='USER_ENTERED')
        return True

    def get_subscribers(self):
        rows = self.ws_subs.get_all_values()
        return rows[1:] if len(rows) > 1 else []

    # ---- Backup ----
    def backup_data(self, backup_filename=None):
        # Not implemented for Sheets; could be implemented via Drive export
        return False


