# BIG thanks to @othalan on StackOverflow for this
# adapted from https://stackoverflow.com/questions/69965175/pyobjc-accessing-mpnowplayinginfocenter

# pylint: disable=no-name-in-module,import-error
from AppKit import (
    NSImage,
    NSMakeRect,
    # NSCompositingOperationSourceOver,
    NSCompositingOperationCopy,
    # NSRunLoop,
    # NSDate,
)
from Foundation import NSMutableDictionary
from MediaPlayer import (
    MPNowPlayingInfoCenter,
    MPNowPlayingInfoPropertyElapsedPlaybackTime,
    MPRemoteCommandCenter,
    MPMediaItemArtwork,
    MPMediaItemPropertyTitle,
    MPMediaItemPropertyArtist,
    MPMediaItemPropertyPlaybackDuration,
    MPMediaItemPropertyArtwork,
    # MPMusicPlaybackState,
    MPMusicPlaybackStatePlaying,
    MPMusicPlaybackStatePaused,
    # MPMusicPlaybackStateStopped,
)

# pylint: enable


class MockQueue:  # enable testing this file
    def put(self, *args, **kwargs):
        pass

    def empty(self):
        return True


class MockInt:
    def __init__(self) -> None:
        self._value = 0

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, value):
        self._value = value


class MacNowPlaying:
    def __init__(self):
        # get the remote command center
        # ... which is how the OS sends commands to the application
        self.cmd_center = MPRemoteCommandCenter.sharedCommandCenter()

        # get the now playing info center
        # ... which is how this application notifies MacOS of what is playing
        self.info_center = MPNowPlayingInfoCenter.defaultCenter()

        # enable command handlers
        self.cmd_center.playCommand().addTargetWithHandler_(self.play_handler)
        self.cmd_center.pauseCommand().addTargetWithHandler_(self.pause_handler)
        self.cmd_center.togglePlayPauseCommand().addTargetWithHandler_(
            self.toggle_handler
        )
        self.cmd_center.nextTrackCommand().addTargetWithHandler_(
            self.next_handler
        )
        self.cmd_center.previousTrackCommand().addTargetWithHandler_(
            self.prev_handler
        )
        self.cmd_center.seekBackwardCommand().addTargetWithHandler_(
            self.seek_backward_handler
        )
        self.cmd_center.seekForwardCommand().addTargetWithHandler_(
            self.seek_forward_handler
        )
        self.cmd_center.changePlaybackPositionCommand().addTargetWithHandler_(
            self.change_position_handler
        )
        # NOTE: disabling these handlers shows prev/next track buttons instead
        # NOTE:  in the control center and touch bar
        self.cmd_center.skipForwardCommand().addTargetWithHandler_(
            self.seek_forward_handler
        )
        self.cmd_center.skipBackwardCommand().addTargetWithHandler_(
            self.seek_backward_handler
        )
        # self.cmd_center.stopCommand().addTargetWithHandler_(self.stop)

        self.title_queue = MockQueue()
        self.artist_queue = MockQueue()
        self.paused = False
        self.pos = 0
        self.length = 0
        self.q = MockQueue()
        self.cover = None

        self.title = ""
        self.artist = ""
        self._cover = None

    def play_handler(self, _event):
        """
        Handle an external 'playCommand' event.
        """
        if self.info_center.playbackState() == MPMusicPlaybackStatePaused:
            self.q.put(" ")

        return 0

    def pause_handler(self, _event):
        """
        Handle an external 'pauseCommand' event.
        """
        if self.info_center.playbackState() == MPMusicPlaybackStatePlaying:
            self.q.put(" ")

        return 0

    def toggle_handler(self, _event):
        """
        Handle an external 'togglePlayPauseCommand' event.
        """
        self.q.put(" ")

        return 0

    def next_handler(self, _event):
        """
        Handle an external 'nextTrackCommand' event.
        """
        self.q.put("n")
        return 0

    def prev_handler(self, _event):
        """
        Handle an external 'previousTrackCommand' event.
        """
        self.q.put("b")
        return 0

    def seek_backward_handler(self, _event):
        """
        Handle an external 'seekBackwardCommand' event.
        """
        self.pos -= 10
        return 0

    def seek_forward_handler(self, _event):
        """
        Handle an external 'seekForwardCommand' event.
        """
        self.pos += 10
        return 0

    def change_position_handler(self, event):
        # get time from event
        time = round(event.positionTime())
        self.pos = time
        return 0

    def stop(self):
        """
        Call this method to update 'Now Playing' state to stopped
        """
        self.q.put("q")
        return 0

    def pause(self):
        """
        Call this method to update 'Now Playing' state to paused
        """
        self.info_center.setPlaybackState_(MPMusicPlaybackStatePaused)
        return 0

    def resume(self):
        """
        Call this method to update 'Now Playing' state to playing
        """
        self.info_center.setPlaybackState_(MPMusicPlaybackStatePlaying)
        return 0

    def update(self):
        """
        Call this method to update the 'Now Playing' info
        """

        nowplaying_info = NSMutableDictionary.dictionary()

        if not self.artist_queue.empty():
            while not self.artist_queue.empty():
                self.artist = ""
                c = self.artist_queue.get()
                while c != "\n":
                    self.artist += c
                    c = self.artist_queue.get()

        if not self.title_queue.empty():
            while not self.title_queue.empty():
                self.title = ""
                c = self.title_queue.get()
                while c != "\n":
                    self.title += c
                    c = self.title_queue.get()

        # Set basic track information
        nowplaying_info[MPMediaItemPropertyTitle] = self.title
        # print("title: {}".format(self.title), file=open("log.txt", "a"))
        nowplaying_info[MPMediaItemPropertyArtist] = self.artist
        # print("artist: {}".format(self.artist), file=open("log.txt", "a"))
        nowplaying_info[MPMediaItemPropertyPlaybackDuration] = self.length
        # print("length: {}".format(self.length), file=open("log.txt", "a"))
        nowplaying_info[MPNowPlayingInfoPropertyElapsedPlaybackTime] = self.pos
        # print("pos: {}".format(self.pos), file=open("log.txt", "a"))

        if self.cover is not None:
            # print("cover len: {}".format(len(self.cover)), file=open("log.txt", "a"))
            img = NSImage.alloc().initWithData_(self.cover)

            def resize(size):
                new = NSImage.alloc().initWithSize_(size)
                new.lockFocus()
                img.drawInRect_fromRect_operation_fraction_(
                    NSMakeRect(0, 0, size.width, size.height),
                    NSMakeRect(0, 0, img.size().width, img.size().height),
                    NSCompositingOperationCopy,
                    1.0,
                )
                new.unlockFocus()
                return new

            art = MPMediaItemArtwork.alloc().initWithBoundsSize_requestHandler_(
                img.size(), resize
            )

            # print("artwork size: {}".format(img.size()))
            nowplaying_info[MPMediaItemPropertyArtwork] = self._cover = art
            self.cover = None
        else:
            if self._cover is not None:
                nowplaying_info[MPMediaItemPropertyArtwork] = self._cover

        # Set the metadata information for the 'Now Playing' service
        self.info_center.setNowPlayingInfo_(nowplaying_info)

        if self.paused:
            self.pause()
        else:
            self.resume()

        # self.info_center.setObject_for_key_(self.artist, "artist")
        # self.info_center.setObject_for_key_(self.length, "length")
        # self.info_center.setObject_for_key_(self.pos, "pos")

        # # self.info_center.title = title
        # # self.info_center.artist = artist
        # # self.info_center.length = length
        # # self.info_center.pos = pos

        # nowplaying_info = NSMutableDictionary.dictionary()

        # nowplaying_info[MPMediaItemPropertyTitle] = title
        # nowplaying_info[MPMediaItemPropertyArtist] = artist
        # nowplaying_info[MPMediaItemPropertyPlaybackDuration] = length
        # nowplaying_info[MPNowPlayingInfoPropertyElapsedPlaybackTime] = pos

        # # self.info_center.setNowPlayingInfo_(nowplaying_info)

        # if paused:
        #     self.info_center.setPlaybackState_(MPMusicPlaybackStatePaused)
        # else:
        #     self.info_center.setPlaybackState_(MPMusicPlaybackStatePlaying)

        return 0
