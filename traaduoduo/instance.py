"""macOS process lock released by the kernel; activate the existing window."""
import hashlib
import sys
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtCore import QLockFile


class MacInstance:
    def __init__(self, directory):
        self.file = None
        self.server = None
        self.owner = True
        self.win_lock=None
        if sys.platform not in ('darwin','win32'):
            return
        self.name = 'TRAADuoDuo-' + hashlib.sha256(str(directory.resolve()).encode()).hexdigest()[:24]
        if sys.platform=='win32':
            self.win_lock=QLockFile(str(directory/'instance-windows.lock'));self.win_lock.setStaleLockTime(0)
            if not self.win_lock.tryLock(0):self.owner=False
            if not self.owner:self.notify_owner();return
            self.listen();return
        import fcntl
        self.file = (directory / 'instance.lock').open('a+b')
        try:
            fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.owner = False
            self.file.close()
            self.file = None
            self.notify_owner()
            return
        self.listen()

    def notify_owner(self):
        socket=QLocalSocket();socket.connectToServer(self.name)
        if socket.waitForConnected(1000):socket.write(b'activate');socket.waitForBytesWritten(1000)
        socket.abort()

    def listen(self):
        self.server = QLocalServer()
        # Only the kernel-lock owner may clear a stale Unix socket.
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            if self.file:self.file.close()
            if self.win_lock:self.win_lock.unlock()
            raise RuntimeError('無法建立程式單一執行個體通道')

    def activate(self, window):
        if self.server:
            def receive():
                while self.server.hasPendingConnections():
                    socket = self.server.nextPendingConnection()
                    socket.close()
                    socket.deleteLater()
                window.showNormal()
                window.raise_()
                window.activateWindow()
            self.server.newConnection.connect(receive)

    def close(self):
        if self.win_lock:self.win_lock.unlock()
        if self.server:
            self.server.close()
        if self.file:
            self.file.close()
            self.file = None
