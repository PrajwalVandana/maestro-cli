# BIG thanks to @othalan on StackOverflow for this
# adapted from https://stackoverflow.com/questions/69965175/pyobjc-accessing-mpnowplayinginfocenter

import atexit
import multiprocessing

# pylint: disable=no-name-in-module,import-error
from AppKit import NSImage
from AppKit import NSMakeRect

# from AppKit import NSEventTrackingRunLoopMode
from AppKit import NSRunLoop

# from AppKit import NSThread
from AppKit import NSCompositingOperationSourceOver
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
    def __init__(self, q=None, pos=None):
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

        if q is None:
            self.q = MockQueue()
        if pos is None:
            self.pos = MockInt()

        self._cover = None

    def play_handler(self, _event):
        """
        Handle an external 'playCommand' event.
        """
        if self.info_center.playbackState() == MPMusicPlaybackStatePaused:
            self.q.put(" ")
            self.resume()

        return 0

    def pause_handler(self, _event):
        """
        Handle an external 'pauseCommand' event.
        """
        if self.info_center.playbackState() == MPMusicPlaybackStatePlaying:
            self.q.put(" ")
            self.pause()

        return 0

    def toggle_handler(self, _event):
        """
        Handle an external 'togglePlayPauseCommand' event.
        """
        self.q.put(" ")

        if self.info_center.playbackState() == MPMusicPlaybackStatePlaying:
            self.pause()
        else:
            self.resume()

        return 0

    def next_handler(self, _event):
        """
        Handle an external 'nextTrackCommand' event.
        """
        self.q.put("s")
        return 0

    def prev_handler(self, _event):
        """
        Handle an external 'previousTrackCommand' event.
        """
        self.q.put("p")
        return 0

    def seek_backward_handler(self, _event):
        """
        Handle an external 'seekBackwardCommand' event.
        """
        self.q.put("LEFT" * 2)  # twice b/c 10 seconds
        return 0

    def seek_forward_handler(self, _event):
        """
        Handle an external 'seekForwardCommand' event.
        """
        self.q.put("RIGHT" * 2)
        return 0

    def change_position_handler(self, event):
        # get time from event
        time = int(event.positionTime())
        self.pos.value = time
        return 0

    def stop(self):
        """
        Call this method to update 'Now Playing' state to stopped
        """
        self.q.put("e")
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

    def play(
        self,
        title: str,
        artist: str,
        paused: bool,
        length: int = 0,
        pos: int = 0,
        cover: bytes = None,
    ):
        """
        Call this method to set the 'Now Playing' info

        length is in seconds
        """

        nowplaying_info = NSMutableDictionary.dictionary()

        # Set basic track information
        nowplaying_info[MPMediaItemPropertyTitle] = title
        nowplaying_info[MPMediaItemPropertyArtist] = artist
        nowplaying_info[MPMediaItemPropertyPlaybackDuration] = length
        nowplaying_info[MPNowPlayingInfoPropertyElapsedPlaybackTime] = pos

        if cover is not None:
            img = NSImage.alloc().initWithData_(cover)

            def resize(size):
                new = NSImage.alloc().initWithSize_(size)
                new.lockFocus()
                img.drawInRect_fromRect_operation_fraction_(
                    NSMakeRect(0, 0, size.width, size.height),
                    NSMakeRect(0, 0, img.size().width, img.size().height),
                    NSCompositingOperationSourceOver,
                    1.0,
                )
                new.unlockFocus()
                return new

            art = MPMediaItemArtwork.alloc().initWithBoundsSize_requestHandler_(
                img.size(), resize
            )

            # print("artwork size: {}".format(img.size()))
            nowplaying_info[MPMediaItemPropertyArtwork] = self._cover = art
        else:
            if self._cover is not None:
                nowplaying_info[MPMediaItemPropertyArtwork] = self._cover

        # Set the metadata information for the 'Now Playing' service
        self.info_center.setNowPlayingInfo_(nowplaying_info)

        if paused:
            self.info_center.setPlaybackState_(MPMusicPlaybackStatePaused)
        else:
            self.info_center.setPlaybackState_(MPMusicPlaybackStatePlaying)

        return 0

    # def update(
    #     self,
    #     title: str,
    #     artist: str,
    #     paused: bool,
    #     length: int = 0,
    #     pos: int = 0,
    # ):
    #     """
    #     Call this method to update the 'Now Playing' info

    #     length is in seconds
    #     """

    #     self.info_center.setObject_for_key_(title, "title")
    #     self.info_center.setObject_for_key_(artist, "artist")
    #     self.info_center.setObject_for_key_(length, "length")
    #     self.info_center.setObject_for_key_(pos, "pos")

    #     # self.info_center.title = title
    #     # self.info_center.artist = artist
    #     # self.info_center.length = length
    #     # self.info_center.pos = pos

    #     nowplaying_info = NSMutableDictionary.dictionary()

    #     nowplaying_info[MPMediaItemPropertyTitle] = title
    #     nowplaying_info[MPMediaItemPropertyArtist] = artist
    #     nowplaying_info[MPMediaItemPropertyPlaybackDuration] = length
    #     nowplaying_info[MPNowPlayingInfoPropertyElapsedPlaybackTime] = pos

    #     # self.info_center.setNowPlayingInfo_(nowplaying_info)

    #     if paused:
    #         self.info_center.setPlaybackState_(MPMusicPlaybackStatePaused)
    #     else:
    #         self.info_center.setPlaybackState_(MPMusicPlaybackStatePlaying)

    #     return 0


def runloop():
    """
    NOTE: This function can't be called in non-main thread.
    """
    nowplaying = MacNowPlaying()
    nowplaying.play("title", "artist", 100)
    print("connected")
    NSRunLoop.currentRunLoop().run()


# runloop()

if __name__ == "__main__":
    main_process = multiprocessing.Process(target=runloop)
    main_process.start()
    atexit.register(main_process.terminate)
    main_process.join()
