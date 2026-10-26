"""macOS process lock released by the kernel; activate the existing window."""
import hashlib
import sys
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class MacInstance:
    def __init__(self, directory):
        self.file = None
        self.server = None
        self.owner = True
        if sys.platform != 'darwin':
            return
        import fcntl
        self.name = 'TRAADuoDuo-' + hashlib.sha256(str(directory.resolve()).encode()).hexdigest()[:24]
        self.file = (directory / 'instance.lock').open('a+b')
        try:
            fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.owner = False
            self.file.close()
            self.file = None
            socket = QLocalSocket()
            socket.connectToServer(self.name)
            if socket.waitForConnected(1000):
                socket.write(b'activate')
                socket.waitForBytesWritten(1000)
            socket.abort()
            return
        self.server = QLocalServer()
        # Only the kernel-lock owner may clear a stale Unix socket.
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            self.file.close()
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
        if self.server:
            self.server.close()
        if self.file:
            self.file.close()
            self.file = None
