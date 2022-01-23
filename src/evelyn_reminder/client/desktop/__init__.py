#  Evelyn Reminder
#  Copyright © 2021  Stefan Schindler
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License in version 3
#  as published by the Free Software Foundation.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import logging
import sys
import webbrowser
from collections.abc import Callable
from contextlib import contextmanager, AbstractContextManager
from typing import Optional

from PySide6.QtCore import Slot, QObject, Signal, QThread, QTimer, QSettings, QSize, QPoint, QDateTime
from PySide6.QtGui import QCloseEvent, Qt, QAction, QContextMenuEvent, QMouseEvent
from PySide6.QtWidgets import (
    QApplication, QLabel, QMenu, QStackedWidget, QWidget, QSizePolicy, QGridLayout, QDialog, QVBoxLayout,
    QDateTimeEdit, QDialogButtonBox, QLineEdit, QCheckBox)

from evelyn_reminder.client import EvelynClient


def main() -> None:
    # noinspection SpellCheckingInspection
    logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.DEBUG)
    # run application
    app = QApplication([])
    widget = EvelynDesktop()
    widget.show()
    sys.exit(app.exec())


class Settings(QSettings):
    DEFAULTS = {
        'netloc': 'example.com',
        'base_path': '/evelyn',
        'api_key': '0000',
        'guild': '000000000000000000',
        'member': '000000000000000000',
        'window_stays_on_top': True,
        'transparent_when_idle': True}

    def __init__(self) -> None:
        super().__init__('Evelyn Reminder', 'Evelyn Desktop')
        self.beginGroup('user')
        for key in self.allKeys():
            if key not in self.DEFAULTS:
                self.remove(key)
        for key, default in self.DEFAULTS.items():
            if not self.contains(key):
                self.setValue(key, default)
        self.endGroup()


class SettingsDialog(QDialog):
    KEYS_BOOL = ['window_stays_on_top', 'transparent_when_idle']

    def __init__(
            self,
            parent: QWidget,
            settings: Settings
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle('Settings')
        self.widgets = {}
        self.setLayout(layout := QGridLayout())
        self.settings.beginGroup('user')
        for index, key in enumerate(self.settings.DEFAULTS):
            if key in self.KEYS_BOOL:
                # noinspection PyTypeChecker
                value: bool = self.settings.value(key, type=bool)
                widget = QCheckBox()
                widget.setChecked(value)
            else:
                # noinspection PyTypeChecker
                value: str = self.settings.value(key, type=str)
                widget = QLineEdit()
                widget.setText(value)
            self.widgets[key] = widget
            layout.addWidget(QLabel(key), index, 0)
            layout.addWidget(widget, index, 1)
        self.settings.endGroup()
        label = QLabel('Please restart the application\nto apply new settings!')
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label, layout.rowCount(), 0, 1, 2)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save ^ QDialogButtonBox.Cancel, self)
        self.buttons.button(QDialogButtonBox.Save).clicked.connect(self.accept)
        self.buttons.button(QDialogButtonBox.Cancel).clicked.connect(self.reject)
        layout.addWidget(self.buttons, layout.rowCount(), 0, 1, 2)

    def accept(self) -> None:
        self.settings.beginGroup('user')
        for key, widget in self.widgets.items():
            if key in self.KEYS_BOOL:
                value = widget.isChecked()
            else:
                value = widget.text()
            self.settings.setValue(key, value)
        self.settings.endGroup()
        super().accept()


class ClickableLabel(QLabel):
    def __init__(
            self,
            text: str,
            func: Callable[[], None]
    ) -> None:
        super().__init__(text)
        self.func = func

    def mouseReleaseEvent(
            self,
            event: QMouseEvent
    ) -> None:
        if event.button() == Qt.LeftButton:
            self.func()
        super().mouseReleaseEvent(event)


class ReportDoneDialog(QDialog):
    def __init__(
            self,
            parent: QWidget
    ) -> None:
        super().__init__(parent)
        self.date_time_edit = QDateTimeEdit()
        self.date_time_edit.setDateTime(QDateTime.currentDateTime())
        self.button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.main_layout = QVBoxLayout()
        self.main_layout.addWidget(self.date_time_edit)
        self.main_layout.addWidget(self.button_box)
        self.setLayout(self.main_layout)
        self.setWindowTitle('Report done')

    def get_date_time(self) -> QDateTime:
        return self.date_time_edit.dateTime()


class EvelynDesktop(QStackedWidget):
    INTERVAL_SECS = 30
    ALERT_SECS = 5

    signal_get_ping = Signal(bool)
    signal_post_history = Signal(int, QDateTime)

    def __init__(self) -> None:
        super().__init__()
        # load settings
        self.settings = Settings()
        # state
        self.state_key: Optional[int] = None
        # label widget
        self.label_ping = ClickableLabel('Loading ...', self.post_history)
        self.label_ping.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        layout_ping = QGridLayout()
        layout_ping.setContentsMargins(0, 0, 0, 0)
        layout_ping.addWidget(self.label_ping)
        self.widget_ping = QWidget()
        self.widget_ping.setLayout(layout_ping)
        self.addWidget(self.widget_ping)
        # alert widget
        self.label_alert = QLabel()
        self.label_alert.setWordWrap(True)
        self.label_alert.setAlignment(Qt.AlignCenter)
        self.label_alert.setStyleSheet(f'background: #dddddd;')
        self.addWidget(self.label_alert)
        # context menu
        self.action_frameless = QAction('Frameless window')
        self.action_frameless.setCheckable(True)
        self.action_frameless.triggered.connect(self.set_frameless_window)
        self.action_report_done = QAction('Report done ...')
        self.action_report_done.triggered.connect(self.report_done)
        self.action_settings = QAction('Settings ...')
        self.action_settings.triggered.connect(self.change_settings)
        self.action_homepage = QAction('Open homepage')
        self.action_homepage.triggered.connect(self.open_homepage)
        self.action_exit = QAction('Exit')
        self.action_exit.triggered.connect(self.close)
        self.context_menu = QMenu()
        self.context_menu.addAction(self.action_frameless)
        self.context_menu.addAction(self.action_report_done)
        self.context_menu.addAction(self.action_settings)
        self.context_menu.addAction(self.action_homepage)
        self.context_menu.addAction(self.action_exit)
        # threads
        self.thread_communication = QThread()
        self.thread_communication.start()
        # workers
        # noinspection PyTypeChecker
        self.worker_communication = CommunicationWorker(
            netloc=self.settings.value('user/netloc', type=str),
            base_path=self.settings.value('user/base_path', type=str),
            api_key=self.settings.value('user/api_key', type=str),
            guild=int(self.settings.value('user/guild', type=str)),
            member=int(self.settings.value('user/member', type=str)))
        self.worker_communication.moveToThread(self.thread_communication)
        # signals
        self.worker_communication.signal_get_ping_done.connect(self.get_ping_done)
        self.worker_communication.signal_post_history_done.connect(self.post_history_done)
        self.signal_get_ping.connect(self.worker_communication.get_ping)
        self.signal_post_history.connect(self.worker_communication.post_history)
        # get ping timer
        QTimer.singleShot(0, self.get_ping)
        self.timer_ping = QTimer()
        self.timer_ping.timeout.connect(self.get_ping)
        self.timer_ping.setTimerType(Qt.VeryCoarseTimer)
        self.timer_ping.start(self.INTERVAL_SECS * 1000)
        # switch label timer
        self.timer_label = QTimer()
        self.timer_label.timeout.connect(lambda: self.setCurrentWidget(self.widget_ping))
        self.timer_label.setSingleShot(True)
        self.timer_label.setTimerType(Qt.CoarseTimer)
        # window attributes
        # noinspection PyTypeChecker
        window_size: Optional[QSize] = self.settings.value('state/window_size')
        if window_size is not None:
            self.resize(window_size)
        # noinspection PyTypeChecker
        window_pos: Optional[QPoint] = self.settings.value('state/window_pos')
        if window_pos is not None:
            self.move(window_pos)
        # noinspection PyTypeChecker
        window_frameless: bool = self.settings.value('state/window_frameless', type=bool)
        if window_frameless:
            QTimer.singleShot(100, self.action_frameless.trigger)
        # noinspection PyTypeChecker
        window_stays_on_top: bool = self.settings.value('user/window_stays_on_top', type=bool)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, window_stays_on_top)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle('Evelyn Reminder')

    def closeEvent(
            self,
            event: QCloseEvent
    ) -> None:
        # save settings
        with suppress_and_log_exception():
            self.settings.setValue('state/window_size', self.size())
            self.settings.setValue('state/window_pos', self.pos())
            self.settings.setValue('state/window_frameless', bool(self.windowFlags() & Qt.FramelessWindowHint))
        # stop communication thread
        with suppress_and_log_exception():
            self.thread_communication.quit()
            self.thread_communication.wait()
        # done
        super().closeEvent(event)

    def contextMenuEvent(
            self,
            event: QContextMenuEvent
    ) -> None:
        self.context_menu.exec(event.globalPos())

    @Slot()
    def get_ping(self) -> None:
        logging.info('Get ping ...')
        self.signal_get_ping.emit(self.settings.value('user/filter_due', type=bool))

    @Slot(int, str, str)
    def get_ping_done(
            self,
            key: int,
            text: str,
            color: str
    ) -> None:
        logging.info('Get ping done')
        if key == -1:
            self.state_key = None
            self.label_ping.setWordWrap(True)
            self.label_ping.setTextFormat(Qt.PlainText)
        else:
            self.state_key = key
            self.label_ping.setWordWrap(False)
            self.label_ping.setTextFormat(Qt.RichText)
        self.label_ping.setText(text)
        self.label_ping.setStyleSheet(f'background : #00000000; ')
        self.widget_ping.setStyleSheet(f'background : {color}; ')

    @Slot()
    def post_history(
            self,
            date_time: QDateTime = QDateTime()
    ) -> None:
        # this method is called as Slot by ClickableLabel.mouseReleaseEvent() without arguments
        # this method is called directly by EvelynDesktop.report_done() with a date_time
        if self.state_key is None:
            return
        logging.info('Post history ...')
        self.label_alert.setText('Sending ...')
        self.label_alert.setStyleSheet(f'background: #dddddd;')
        self.setCurrentWidget(self.label_alert)
        self.signal_post_history.emit(self.state_key, date_time)

    @Slot(str, bool)
    def post_history_done(
            self,
            text: str,
            error: bool
    ) -> None:
        logging.info('Post history done')
        self.label_alert.setText(text)
        if error:
            self.label_alert.setStyleSheet(f'background: #dd4b4b;')
        self.timer_label.start(self.ALERT_SECS * 1000)
        # trigger instant ping update to avoid outdated info
        self.timer_ping.stop()
        self.timer_ping.start(self.INTERVAL_SECS * 1000)
        self.get_ping()

    @Slot()
    def report_done(self) -> None:
        self.timer_ping.stop()  # stop ping update while dialog is open
        report_done_dialog = ReportDoneDialog(self)
        response = report_done_dialog.exec()
        if response != QDialog.Accepted:
            self.timer_ping.start(self.INTERVAL_SECS * 1000)
            self.get_ping()
            return
        date_time = report_done_dialog.get_date_time()
        self.post_history(date_time)

    @Slot(bool)
    def set_frameless_window(
            self,
            value: bool
    ) -> None:
        pos = self.pos()
        self.setWindowFlag(Qt.FramelessWindowHint, value)
        # workaround: window goes invisible otherwise
        self.setVisible(True)
        # workaround: window would move up otherwise
        if value:
            QTimer.singleShot(100, lambda: self.move(pos))

    @Slot()
    def open_homepage(self) -> None:
        webbrowser.open('https://github.com/stefs/evelyn-reminder')

    @Slot()
    def change_settings(self) -> None:
        SettingsDialog(parent=self, settings=self.settings).exec()


class CommunicationWorker(QObject):
    signal_get_ping_done = Signal(int, str, str)
    signal_post_history_done = Signal(str, bool)

    def __init__(
            self,
            netloc: str,
            base_path: str,
            api_key: str,
            guild: int,
            member: int
    ) -> None:
        super().__init__()
        self.client = EvelynClient(netloc=netloc, base_path=base_path, api_key=api_key)
        self.guild = guild
        self.member = member

    @Slot(bool)
    def get_ping(
            self,
            filter_due: bool
    ) -> None:
        try:
            key = -1
            flag_due = False
            text = ''
            color = ''
            for ping in self.client.get_ping(guild=self.guild, member=self.member,
                                             filter_ping_due=False, filter_due=filter_due):
                key_ = ping['reminder']['key']
                flag_due_ = ping['flag_due']
                if key == -1 or (flag_due and flag_due_ and key_ < key) or (not flag_due and key_ < key):
                    key = key_
                    flag_due = flag_due_
                    message = ping['message']
                    when = ping['when']
                    last = ping['last']
                    gaps = ping['gaps']
                    schedule = ping['schedule']
                    text = (f'<b>{message}</b><br>'
                            f'<b>{when}</b><br>'
                            f'<b>Last:</b> {last}<br>'
                            f'<b>Gaps:</b> {gaps}<br>'
                            f'<b>Schedule:</b> {schedule}')
                    color = ping['reminder']['color_hex']
                if not flag_due:
                    color = '#77444444'
        except Exception as e:
            key = -1
            text = str(e)
            color = '#dd4b4b'
        self.signal_get_ping_done.emit(key, text, color)

    @Slot(int, QDateTime)
    def post_history(
            self,
            key: int,
            date_time: QDateTime
    ) -> None:
        try:
            data = self.client.post_history(
                guild=self.guild, member=self.member, key=key,
                time_utc=date_time.toPython() if date_time else None)
            text = str(data['message'])
            error = False
        except Exception as e:
            text = str(e)
            error = True
        self.signal_post_history_done.emit(text, error)


@contextmanager
def suppress_and_log_exception() -> AbstractContextManager:
    try:
        yield
    except Exception as e:
        logging.error(f'{type(e).__name__}: {e}')
