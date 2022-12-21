import os


class Scroller:
    def __init__(self, num_lines, win_size):
        self.num_lines = num_lines
        self.win_size = win_size
        self.pos = 0
        self.top = 0

    def scroll_forward(self):
        if self.pos < self.num_lines - 1:
            if (
                self.pos == self.halfway
                and self.top < self.num_lines - self.win_size
            ):
                self.top += 1
            self.pos += 1

    def scroll_backward(self):
        if self.pos > 0:
            if self.pos == self.halfway and self.top > 0:
                self.top -= 1
            self.pos -= 1

    @property
    def halfway(self):
        return self.top + self.win_size // 2

    def resize(self, win_size):
        self.win_size = win_size
        self.top = max(0, self.pos - self.win_size // 2)
        self.top = max(0, min(self.num_lines - self.win_size, self.top))


def clear_screen():
    if os.name == "posix":
        os.system("clear")
    else:
        click.clear()


class AppDelegate(NSObject):
    def applicationDidFinishLaunching_(self, _aNotification):
        pass

    def sayHello_(self, _sender):
        pass


def app_helper_loop():
    # ns_application = NSApplication.sharedApplication()
    # logo_ns_image = NSImage.alloc().initByReferencingFile_(
    #     "./maestro_icon.png"
    # )
    # ns_application.setApplicationIconImage_(logo_ns_image)

    # # we must keep a reference to the delegate object ourselves,
    # # NSApp.setDelegate_() doesn't retain it. A local variable is
    # # enough here.
    # delegate = AppDelegate.alloc().init()
    # NSApp().setDelegate_(delegate)

    AppHelper.runEventLoop()


def discord_presence_loop(song_name_queue):
    try:
        discord_rpc = pypresence.Presence(client_id=1039038199881810040)
        discord_rpc.connect()
        discord_connected = True
    except:  # pylint: disable=bare-except
        discord_connected = False

    while True:
        if not discord_connected:
            try:
                discord_rpc = pypresence.Presence(
                    client_id=1039038199881810040
                )
                discord_rpc.connect()
                discord_connected = True
            except:  # pylint: disable=bare-except
                pass

        song_name = ""
        if not song_name_queue.empty() or song_name:
            while not song_name_queue.empty():
                song_name = ""
                c = song_name_queue.get()
                while c != "\n":
                    song_name += c
                    c = song_name_queue.get()

            if discord_connected:
                try:
                    discord_rpc.update(
                        details="Listening to",
                        state=song_name,
                        large_image="maestro-icon",
                    )
                    song_name = ""
                    sleep(15)
                except:  # pylint: disable=bare-except
                    discord_connected = False
            else:
                try:
                    discord_rpc = pypresence.Presence(
                        client_id=1039038199881810040
                    )
                    discord_rpc.connect()
                    discord_connected = True
                except:  # pylint: disable=bare-except
                    pass

                if discord_connected:
                    try:
                        discord_rpc.update(
                            details="Listening to",
                            state=song_name,
                            large_image="maestro-icon",
                        )
                        song_name = ""
                        sleep(15)
                    except:  # pylint: disable=bare-except
                        discord_connected = False


def fit_string_to_width(string, width, length_so_far):
    line_over = False
    if length_so_far + len(string) > width:
        line_over = True
        remaining_width = width - length_so_far
        if remaining_width >= 3:
            string = string[: (remaining_width - 3)].rstrip() + "...\n"
        else:
            string = "..."[:remaining_width] + "\n"
    length_so_far += len(string)
    return string, length_so_far, line_over


def addstr_fit_to_width(
    stdscr, string, width, length_so_far, line_over, *args, **kwargs
):
    if not line_over:
        string, length_so_far, line_over = fit_string_to_width(
            string, width, length_so_far
        )
        if string:
            stdscr.addstr(string, *args, **kwargs)
    return length_so_far, line_over


def output(
    stdscr,
    scroller,
    i,
    playlist,
    looping,
    volume,
    duration,
    pos,
    paused,
    adding_song,
):
    # NOTE: terminal prints newline for some reason if len(string) == width, so
    # NOTE:   we subtract 1
    screen_width = stdscr.getmaxyx()[1] - 1

    for j in range(scroller.top, scroller.top + scroller.win_size):
        if j > len(playlist) - 1:
            stdscr.addstr("\n")
        else:
            length_so_far, line_over = 0, False

            length_so_far, line_over = addstr_fit_to_width(
                stdscr,
                f"{j + 1} ",
                screen_width,
                length_so_far,
                line_over,
                curses.color_pair(2),
            )
            if j == i:
                length_so_far, line_over = addstr_fit_to_width(
                    stdscr,
                    f"{playlist[j][1]} ",
                    screen_width,
                    length_so_far,
                    line_over,
                    curses.color_pair(3) | curses.A_BOLD,
                )
                length_so_far, line_over = addstr_fit_to_width(
                    stdscr,
                    f"({playlist[j][0]}) ",
                    screen_width,
                    length_so_far,
                    line_over,
                    curses.color_pair(3),
                )
            else:
                length_so_far, line_over = addstr_fit_to_width(
                    stdscr,
                    f"{playlist[j][1]} ({playlist[j][0]}) ",
                    screen_width,
                    length_so_far,
                    line_over,
                    (
                        curses.color_pair(4)
                        if (j == scroller.pos)
                        else curses.color_pair(1)
                    ),
                )
            length_so_far, line_over = addstr_fit_to_width(
                stdscr,
                f"{', '.join(playlist[j][2].split(','))}\n",
                screen_width,
                length_so_far,
                line_over,
                curses.color_pair(2),
            )

    if adding_song is not None:
        adding_song_length, line_over = addstr_fit_to_width(
            stdscr,
            "Add song (by ID): " + adding_song[0] + "\n",
            screen_width,
            0,
            False,
            curses.color_pair(1),
        )
        if line_over:
            adding_song_length -= 1  # newline doesn't count

    length_so_far, line_over = 0, False

    length_so_far, line_over = addstr_fit_to_width(
        stdscr,
        ("| " if paused else "> ") + f"({playlist[i][0]}) ",
        screen_width,
        length_so_far,
        line_over,
        curses.color_pair(13),
    )
    length_so_far, line_over = addstr_fit_to_width(
        stdscr,
        f"{playlist[i][1]} ",
        screen_width,
        length_so_far,
        line_over,
        curses.color_pair(13) | curses.A_BOLD,
    )
    volume_line_length_so_far, line_over = addstr_fit_to_width(
        stdscr,
        "%d/%d  " % (i + 1, len(playlist)),
        screen_width,
        length_so_far,
        line_over,
        curses.color_pair(12),
    )
    if not line_over:
        addstr_fit_to_width(
            stdscr,
            " " * (screen_width - length_so_far),
            screen_width,
            volume_line_length_so_far,
            line_over,
            curses.color_pair(13),
        )
        # stdscr.addstr("\n")

    length_so_far, line_over = 0, False
    secs = int(pos)
    length_so_far, line_over = addstr_fit_to_width(
        stdscr,
        f"{secs//60:02}:{secs%60:02} / {duration//60:02}:{duration%60:02}  ",
        screen_width,
        length_so_far,
        line_over,
        curses.color_pair(15),
    )
    if not line_over:
        if screen_width - length_so_far >= MIN_PROGRESS_BAR_WIDTH + 2:
            progress_bar_width = screen_width - length_so_far - 2
            bar = "|"
            progress_block_width = (progress_bar_width * 8 * pos) // duration
            for _ in range(progress_bar_width):
                if progress_block_width > 8:
                    bar += HORIZONTAL_BLOCKS[8]
                    progress_block_width -= 8
                elif progress_block_width > 0:
                    bar += HORIZONTAL_BLOCKS[progress_block_width]
                    progress_block_width = 0
                else:
                    bar += " "
            bar += "|"

            length_so_far, line_over = addstr_fit_to_width(
                stdscr,
                bar,
                screen_width,
                length_so_far,
                line_over,
                curses.color_pair(15),
            )
        else:
            length_so_far, line_over = addstr_fit_to_width(
                stdscr,
                " " * (screen_width - length_so_far),
                screen_width,
                length_so_far,
                line_over,
                curses.color_pair(13),
            )
    # if not line_over:
    #     addstr_fit_to_width(
    #         stdscr,
    #         " " * (screen_width - length_so_far),
    #         screen_width,
    #         length_so_far,
    #         line_over,
    #         curses.color_pair(13),
    #     )

    try:
        # right align volume bar to (progress bar) length_so_far
        stdscr.move(stdscr.getmaxyx()[0] - 2, volume_line_length_so_far)
        # volume_line_length_so_far, line_over = addstr_fit_to_width(
        #     stdscr,
        #     f"vol: {str(int(volume*100)).rjust(3)}/100 ",
        #     screen_width,
        #     volume_line_length_so_far,
        #     line_over,
        #     curses.color_pair(16),
        # )
        if (
            length_so_far - volume_line_length_so_far
            >= MIN_VOLUME_BAR_WIDTH + 10
        ):
            volume_bar_width = min(
                length_so_far - volume_line_length_so_far - 10,
                MAX_VOLUME_BAR_WIDTH,
            )
            bar = f"{str(int(volume*100)).rjust(3)}/100 |"
            block_width = int(volume_bar_width * 8 * volume)
            for _ in range(volume_bar_width):
                if block_width > 8:
                    bar += HORIZONTAL_BLOCKS[8]
                    block_width -= 8
                elif block_width > 0:
                    bar += HORIZONTAL_BLOCKS[block_width]
                    block_width = 0
                else:
                    bar += " "
            bar += "|"
            bar = bar.rjust(length_so_far - volume_line_length_so_far)

            length_so_far, line_over = addstr_fit_to_width(
                stdscr,
                bar,
                length_so_far,
                volume_line_length_so_far,
                line_over,
                curses.color_pair(16),
            )
            # addstr_fit_to_width(
            #     stdscr,
            #     " " * (screen_width - length_so_far),
            #     screen_width,
            #     length_so_far,
            #     line_over,
            #     curses.color_pair(13),
            # )
        elif length_so_far - volume_line_length_so_far >= 7:
            length_so_far, line_over = addstr_fit_to_width(
                stdscr,
                f"{str(int(volume*100)).rjust(3)}/100".rjust(
                    length_so_far - volume_line_length_so_far
                ),
                length_so_far,
                volume_line_length_so_far,
                line_over,
                curses.color_pair(16),
            )
            addstr_fit_to_width(
                stdscr,
                " " * (screen_width - length_so_far),
                screen_width,
                length_so_far,
                line_over,
                curses.color_pair(13),
            )
    except curses.error:
        pass
    if adding_song is not None:
        # adding_song_length-1 b/c 0-indexed
        stdscr.move(
            stdscr.getmaxyx()[0] - 3,
            adding_song_length - 1 + (adding_song[1] - len(adding_song[0])),
        )


def _add(path, tags, move_, songs_file, lines, song_id, prepend_newline):
    song_name = os.path.split(path)[1]
    dest_path = os.path.join(SONGS_DIR, song_name)

    for line in lines:
        details = line.split("|")
        if details[1] == song_name:
            click.secho(
                f"Song with name '{song_name}' already exists", fg="red"
            )
            return

    if move_:
        move(path, dest_path)
    else:
        copy(path, dest_path)

    tags = list(set(tags))

    if prepend_newline:
        songs_file.write("\n")
    songs_file.write(f"{song_id}|{song_name}|{','.join(tags)}\n")

    if not tags:
        tags_string = ""
    elif len(tags) == 1:
        tags_string = f' and tag "{tags[0]}"'
    else:
        tags_string = f" and tags {', '.join([repr(tag) for tag in tags])}"
    click.secho(
        f"Added song '{song_name}' with id {song_id}" + tags_string, fg="green"
    )


def _play(stdscr, playlist, volume, loop, reshuffle, update_discord):
    global can_mac_now_playing  # pylint: disable=global-statement

    # region curses setup
    curses.start_color()
    curses.curs_set(False)
    curses.use_default_colors()
    stdscr.nodelay(True)
    curses.set_escdelay(25)  # 25 ms

    # region colors
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    if curses.can_change_color():
        curses.init_pair(2, curses.COLOR_BLACK + 8, -1)
    else:
        curses.init_pair(2, curses.COLOR_BLACK, -1)
    curses.init_pair(3, curses.COLOR_BLUE, -1)
    curses.init_pair(4, curses.COLOR_RED, -1)
    curses.init_pair(5, curses.COLOR_YELLOW, -1)
    curses.init_pair(6, curses.COLOR_GREEN, -1)
    # curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_GREEN)
    # curses.init_pair(8, curses.COLOR_BLACK, curses.COLOR_GREEN)
    # curses.init_pair(9, curses.COLOR_BLUE, curses.COLOR_GREEN)
    # curses.init_pair(10, curses.COLOR_YELLOW, curses.COLOR_GREEN)
    # curses.init_pair(11, curses.COLOR_GREEN, curses.COLOR_GREEN)
    if curses.can_change_color():
        curses.init_pair(12, curses.COLOR_BLACK + 8, curses.COLOR_BLACK)
    else:
        curses.init_pair(12, curses.COLOR_WHITE, curses.COLOR_BLACK)
    curses.init_pair(13, curses.COLOR_BLUE, curses.COLOR_BLACK)
    curses.init_pair(14, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(15, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(16, curses.COLOR_GREEN, curses.COLOR_BLACK)
    # endregion

    # endregion

    scroller = Scroller(
        len(playlist), stdscr.getmaxyx()[0] - 2  # -2 for status bar
    )

    if loop:
        next_playlist = playlist[:]
        if reshuffle:
            shuffle(next_playlist)
    else:
        next_playlist = None

    if update_discord:
        discord_song_name_queue = multiprocessing.SimpleQueue()
        discord_presence_process = multiprocessing.Process(
            daemon=True,
            target=discord_presence_loop,
            args=(discord_song_name_queue,),
        )
        discord_presence_process.start()

    if sys.platform == "darwin" and can_mac_now_playing:
        mac_now_playing.title = "maestro-cli"
        mac_now_playing.artist_queue = Queue()
        mac_now_playing.q = Queue()
        mac_now_playing.cover = cover_img

        ns_application = NSApplication.sharedApplication()
        # logo_ns_image = NSImage.alloc().initByReferencingFile_(
        #     "./maestro_icon.png"
        # )
        # ns_application.setApplicationIconImage_(logo_ns_image)
        ns_application.setActivationPolicy_(
            NSApplicationActivationPolicyProhibited
        )

        # NOTE: keep reference to delegate object, setDelegate_ doesn't retain
        delegate = AppDelegate.alloc().init()
        NSApp().setDelegate_(delegate)

        app_helper_process = multiprocessing.Process(
            daemon=True,
            target=app_helper_loop,
        )
        app_helper_process.start()

    i = 0
    adding_song: None | tuple = None
    prev_volume = volume
    while i in range(len(playlist)):
        paused = False
        mac_now_playing.paused = paused

        song_path = os.path.join(SONGS_DIR, playlist[i][1])
        duration = int(TinyTag.get(song_path).duration)

        if sys.platform == "darwin" and can_mac_now_playing:
            mac_now_playing.length = duration
            mac_now_playing.pos = 0

            for c in playlist[i][1]:
                mac_now_playing.artist_queue.put(c)
            mac_now_playing.artist_queue.put("\n")

            update_now_playing = True

        if update_discord:
            for c in playlist[i][1]:
                discord_song_name_queue.put(c)
            discord_song_name_queue.put("\n")

        playback = Playback()
        playback.load_file(song_path)
        playback.play()
        playback.set_volume(volume)

        stdscr.clear()
        output(
            stdscr,
            scroller,
            i,
            playlist,
            loop,
            volume,
            duration,
            playback.curr_pos,
            paused,
            adding_song,
        )
        stdscr.refresh()

        frame_duration = 1

        last_timestamp = playback.curr_pos
        next_song = 1  # -1 if going back, 0 if restarting, +1 if next song
        while True:
            if not playback.active:
                next_song = 1
                break

            if sys.platform == "darwin" and can_mac_now_playing:
                try:
                    if update_now_playing:
                        mac_now_playing.update()
                        update_now_playing = False
                    NSRunLoop.currentRunLoop().runUntilDate_(
                        NSDate.dateWithTimeIntervalSinceNow_(0.1)
                    )
                except:  # pylint: disable=bare-except
                    can_mac_now_playing = False

            if (
                sys.platform == "darwin"
                and can_mac_now_playing
                and not mac_now_playing.q.empty()
            ):
                c = mac_now_playing.q.get()
                if c in "nNsS":
                    if i == len(playlist) - 1 and not loop:
                        pass
                    else:
                        next_song = 1
                        playback.stop()
                        break
                elif c in "bBpP":
                    if i == 0:
                        pass
                    else:
                        next_song = -1
                        playback.stop()
                        break
                elif c in "rR":
                    playback.stop()
                    next_song = 0
                    break
                elif c in "eEqQ":
                    playback.stop()
                    return
                elif c == " ":
                    paused = not paused

                    if paused:
                        playback.pause()
                    else:
                        playback.resume()

                    if sys.platform == "darwin" and can_mac_now_playing:
                        mac_now_playing.paused = paused
                        if paused:
                            mac_now_playing.pause()
                        else:
                            mac_now_playing.resume()
                        update_now_playing = True

                    stdscr.clear()
                    output(
                        stdscr,
                        scroller,
                        i,
                        playlist,
                        loop,
                        volume,
                        duration,
                        playback.curr_pos,
                        paused,
                        adding_song,
                    )
                    stdscr.refresh()
            else:
                c = stdscr.getch()
                if c != -1:
                    if adding_song is None:
                        if c == curses.KEY_LEFT:
                            playback.seek(playback.curr_pos - SCRUB_TIME)
                            if sys.platform == "darwin" and can_mac_now_playing:
                                mac_now_playing.pos = round(playback.curr_pos)
                                update_now_playing = True

                            last_timestamp = playback.curr_pos
                            stdscr.clear()
                            output(
                                stdscr,
                                scroller,
                                i,
                                playlist,
                                loop,
                                volume,
                                duration,
                                playback.curr_pos,
                                paused,
                                adding_song,
                            )
                            stdscr.refresh()
                        elif c == curses.KEY_RIGHT:
                            playback.seek(playback.curr_pos + SCRUB_TIME)
                            if sys.platform == "darwin" and can_mac_now_playing:
                                mac_now_playing.pos = round(playback.curr_pos)
                                update_now_playing = True

                            last_timestamp = playback.curr_pos
                            stdscr.clear()
                            output(
                                stdscr,
                                scroller,
                                i,
                                playlist,
                                loop,
                                volume,
                                duration,
                                playback.curr_pos,
                                paused,
                                adding_song,
                            )
                            stdscr.refresh()
                        elif c == curses.KEY_UP:
                            if scroller.pos != 0:
                                scroller.scroll_backward()
                                stdscr.clear()
                                output(
                                    stdscr,
                                    scroller,
                                    i,
                                    playlist,
                                    loop,
                                    volume,
                                    duration,
                                    playback.curr_pos,
                                    paused,
                                    adding_song,
                                )
                                stdscr.refresh()
                        elif c == curses.KEY_DOWN:
                            if scroller.pos != scroller.num_lines - 1:
                                scroller.scroll_forward()
                                stdscr.clear()
                                output(
                                    stdscr,
                                    scroller,
                                    i,
                                    playlist,
                                    loop,
                                    volume,
                                    duration,
                                    playback.curr_pos,
                                    paused,
                                    adding_song,
                                )
                                stdscr.refresh()
                        elif c == curses.KEY_ENTER:
                            i = scroller.pos - 1
                            next_song = 1
                            playback.stop()
                            break
                        elif c == curses.KEY_RESIZE:
                            screen_size = stdscr.getmaxyx()
                            scroller.resize(screen_size[0] - 2)
                            stdscr.clear()
                            output(
                                stdscr,
                                scroller,
                                i,
                                playlist,
                                loop,
                                volume,
                                duration,
                                playback.curr_pos,
                                paused,
                                adding_song,
                            )
                            stdscr.refresh()
                        else:
                            try:
                                c = chr(c)
                                if c in "nNsS":
                                    if i == len(playlist) - 1 and not loop:
                                        pass
                                    else:
                                        next_song = 1
                                        playback.stop()
                                        break
                                elif c in "bBpP":
                                    if i == 0:
                                        pass
                                    else:
                                        next_song = -1
                                        playback.stop()
                                        break
                                elif c in "rR":
                                    playback.stop()
                                    next_song = 0
                                    break
                                elif c in "eEqQ":
                                    playback.stop()
                                    return
                                elif c in "dD":
                                    selected_song = scroller.pos
                                    del playlist[selected_song]
                                    scroller.num_lines -= 1
                                    if (
                                        selected_song == i
                                    ):  # deleted current song
                                        next_song = 1
                                        # will be incremented to i
                                        scroller.pos = i - 1
                                        i -= 1
                                        playback.stop()
                                        break
                                    # deleted song before current
                                    if selected_song < i:
                                        i -= 1
                                elif c in "aA":
                                    adding_song = "", 0
                                    curses.curs_set(True)
                                    screen_size = stdscr.getmaxyx()
                                    scroller.resize(screen_size[0] - 3)
                                    stdscr.clear()
                                    output(
                                        stdscr,
                                        scroller,
                                        i,
                                        playlist,
                                        loop,
                                        volume,
                                        duration,
                                        playback.curr_pos,
                                        paused,
                                        adding_song,
                                    )
                                    stdscr.refresh()
                                elif c in "mM":
                                    if volume == 0:
                                        volume = prev_volume
                                    else:
                                        volume = 0
                                    playback.set_volume(volume)

                                    stdscr.clear()
                                    output(
                                        stdscr,
                                        scroller,
                                        i,
                                        playlist,
                                        loop,
                                        volume,
                                        duration,
                                        playback.curr_pos,
                                        paused,
                                        adding_song,
                                    )
                                    stdscr.refresh()
                                elif c == " ":
                                    paused = not paused

                                    if paused:
                                        playback.pause()
                                    else:
                                        playback.resume()

                                    if (
                                        sys.platform == "darwin"
                                        and can_mac_now_playing
                                    ):
                                        mac_now_playing.paused = paused
                                        if paused:
                                            mac_now_playing.pause()
                                        else:
                                            mac_now_playing.resume()
                                        update_now_playing = True

                                    stdscr.clear()
                                    output(
                                        stdscr,
                                        scroller,
                                        i,
                                        playlist,
                                        loop,
                                        volume,
                                        duration,
                                        playback.curr_pos,
                                        paused,
                                        adding_song,
                                    )
                                    stdscr.refresh()
                                elif c == "[":
                                    volume = max(0, volume - VOLUME_STEP)
                                    playback.set_volume(volume)

                                    stdscr.clear()
                                    output(
                                        stdscr,
                                        scroller,
                                        i,
                                        playlist,
                                        loop,
                                        volume,
                                        duration,
                                        playback.curr_pos,
                                        paused,
                                        adding_song,
                                    )
                                    stdscr.refresh()

                                    prev_volume = volume
                                elif c == "]":
                                    volume = min(1, volume + VOLUME_STEP)
                                    playback.set_volume(volume)

                                    stdscr.clear()
                                    output(
                                        stdscr,
                                        scroller,
                                        i,
                                        playlist,
                                        loop,
                                        volume,
                                        duration,
                                        playback.curr_pos,
                                        paused,
                                        adding_song,
                                    )
                                    stdscr.refresh()

                                    prev_volume = volume
                                elif c in "\r\n":
                                    i = scroller.pos - 1
                                    next_song = 1
                                    playback.stop()
                                    break
                            except (ValueError, OverflowError):
                                pass
                    else:
                        if c == curses.KEY_RESIZE:
                            screen_size = stdscr.getmaxyx()
                            scroller.resize(screen_size[0] - 3)
                            stdscr.clear()
                            output(
                                stdscr,
                                scroller,
                                i,
                                playlist,
                                loop,
                                volume,
                                duration,
                                playback.curr_pos,
                                paused,
                                adding_song,
                            )
                            stdscr.refresh()
                        elif c == curses.KEY_LEFT:
                            # pylint: disable=unsubscriptable-object
                            adding_song = adding_song[0], max(
                                adding_song[1] - 1, 0
                            )
                            stdscr.clear()
                            output(
                                stdscr,
                                scroller,
                                i,
                                playlist,
                                loop,
                                volume,
                                duration,
                                playback.curr_pos,
                                paused,
                                adding_song,
                            )
                            stdscr.refresh()
                        elif c == curses.KEY_RIGHT:
                            # pylint: disable=unsubscriptable-object
                            adding_song = adding_song[0], min(
                                adding_song[1] + 1, len(adding_song[0])
                            )
                            stdscr.clear()
                            output(
                                stdscr,
                                scroller,
                                i,
                                playlist,
                                loop,
                                volume,
                                duration,
                                playback.curr_pos,
                                paused,
                                adding_song,
                            )
                            stdscr.refresh()
                        elif c == curses.KEY_UP:
                            if scroller.pos != 0:
                                scroller.scroll_backward()
                                stdscr.clear()
                                output(
                                    stdscr,
                                    scroller,
                                    i,
                                    playlist,
                                    loop,
                                    volume,
                                    duration,
                                    playback.curr_pos,
                                    paused,
                                    adding_song,
                                )
                                stdscr.refresh()
                        elif c == curses.KEY_DOWN:
                            if scroller.pos != scroller.num_lines - 1:
                                scroller.scroll_forward()
                                stdscr.clear()
                                output(
                                    stdscr,
                                    scroller,
                                    i,
                                    playlist,
                                    loop,
                                    volume,
                                    duration,
                                    playback.curr_pos,
                                    paused,
                                    adding_song,
                                )
                                stdscr.refresh()
                        elif c == curses.KEY_DC:
                            # pylint: disable=unsubscriptable-object
                            if adding_song[1] > 0:
                                adding_song = (
                                    adding_song[0][: adding_song[1] - 1]
                                    + adding_song[0][adding_song[1] :],
                                    adding_song[1] - 1,
                                )
                            stdscr.clear()
                            output(
                                stdscr,
                                scroller,
                                i,
                                playlist,
                                loop,
                                volume,
                                duration,
                                playback.curr_pos,
                                paused,
                                adding_song,
                            )
                            stdscr.refresh()
                        elif c == curses.KEY_ENTER:
                            # pylint: disable=unsubscriptable-object
                            if adding_song[0].isnumeric():
                                for details in playlist:
                                    if int(details[0]) == int(adding_song[0]):
                                        break
                                else:
                                    with open(
                                        SONGS_INFO_PATH,
                                        "r",
                                        encoding="utf-8",
                                    ) as songs_file:
                                        for line in songs_file:
                                            details = line.strip().split("|")
                                            song_id = int(details[0])
                                            if song_id == int(adding_song[0]):
                                                playlist.append(details)
                                                if loop:
                                                    if reshuffle:
                                                        next_playlist.insert(
                                                            randint(
                                                                0,
                                                                len(
                                                                    next_playlist
                                                                )
                                                                - 1,
                                                            ),
                                                            details,
                                                        )
                                                    else:
                                                        next_playlist.append(
                                                            details
                                                        )
                                                scroller.num_lines += 1
                                                adding_song = None
                                                curses.curs_set(False)
                                                scroller.resize(
                                                    screen_size[0] - 2
                                                )
                                                stdscr.clear()
                                                output(
                                                    stdscr,
                                                    scroller,
                                                    i,
                                                    playlist,
                                                    loop,
                                                    volume,
                                                    duration,
                                                    playback.curr_pos,
                                                    paused,
                                                    adding_song,
                                                )
                                                stdscr.refresh()
                                                break
                        elif c == 27:  # ESC key
                            adding_song = None
                            curses.curs_set(False)
                            scroller.resize(screen_size[0] - 2)
                            stdscr.clear()
                            output(
                                stdscr,
                                scroller,
                                i,
                                playlist,
                                loop,
                                volume,
                                duration,
                                playback.curr_pos,
                                paused,
                                adding_song,
                            )
                            stdscr.refresh()
                        else:
                            try:
                                c = chr(c)
                                if c in "\r\n":
                                    # pylint: disable=unsubscriptable-object
                                    if adding_song[0].isnumeric():
                                        for details in playlist:
                                            if int(details[0]) == int(
                                                adding_song[0]
                                            ):
                                                break
                                        else:
                                            with open(
                                                SONGS_INFO_PATH,
                                                "r",
                                                encoding="utf-8",
                                            ) as songs_file:
                                                for line in songs_file:
                                                    details = (
                                                        line.strip().split("|")
                                                    )
                                                    song_id = int(details[0])
                                                    if song_id == int(
                                                        adding_song[0]
                                                    ):
                                                        playlist.append(details)
                                                        if loop:
                                                            if reshuffle:
                                                                next_playlist.insert(
                                                                    randint(
                                                                        0,
                                                                        len(
                                                                            next_playlist
                                                                        )
                                                                        - 1,
                                                                    ),
                                                                    details,
                                                                )
                                                            else:
                                                                next_playlist.append(
                                                                    details
                                                                )
                                                        scroller.num_lines += 1
                                                        adding_song = None
                                                        curses.curs_set(False)
                                                        scroller.resize(
                                                            screen_size[0] - 2
                                                        )
                                                        stdscr.clear()
                                                        output(
                                                            stdscr,
                                                            scroller,
                                                            i,
                                                            playlist,
                                                            loop,
                                                            volume,
                                                            duration,
                                                            playback.curr_pos,
                                                            paused,
                                                            adding_song,
                                                        )
                                                        stdscr.refresh()
                                                        break
                                elif c in "\b\x7f":
                                    # pylint: disable=unsubscriptable-object
                                    if adding_song[1] > 0:
                                        adding_song = (
                                            adding_song[0][: adding_song[1] - 1]
                                            + adding_song[0][adding_song[1] :],
                                            adding_song[1] - 1,
                                        )
                                    stdscr.clear()
                                    output(
                                        stdscr,
                                        scroller,
                                        i,
                                        playlist,
                                        loop,
                                        volume,
                                        duration,
                                        playback.curr_pos,
                                        paused,
                                        adding_song,
                                    )
                                    stdscr.refresh()
                                else:
                                    adding_song = (
                                        # pylint: disable=unsubscriptable-object
                                        adding_song[0][: adding_song[1]]
                                        + c
                                        + adding_song[0][adding_song[1] :],
                                        adding_song[1] + 1,
                                    )
                                    stdscr.clear()
                                    output(
                                        stdscr,
                                        scroller,
                                        i,
                                        playlist,
                                        loop,
                                        volume,
                                        duration,
                                        playback.curr_pos,
                                        paused,
                                        adding_song,
                                    )
                                    stdscr.refresh()
                            except (ValueError, OverflowError):
                                pass

            if sys.platform == "darwin" and can_mac_now_playing:
                if abs(mac_now_playing.pos - playback.curr_pos) > 2:
                    playback.seek(mac_now_playing.pos)
                    last_timestamp = mac_now_playing.pos
                    update_now_playing = True
                    stdscr.clear()
                    output(
                        stdscr,
                        scroller,
                        i,
                        playlist,
                        loop,
                        volume,
                        duration,
                        playback.curr_pos,
                        paused,
                        adding_song,
                    )
                    stdscr.refresh()
                else:
                    mac_now_playing.pos = round(playback.curr_pos)

            if abs(playback.curr_pos - last_timestamp) > frame_duration:
                last_timestamp = playback.curr_pos
                stdscr.clear()
                output(
                    stdscr,
                    scroller,
                    i,
                    playlist,
                    loop,
                    volume,
                    duration,
                    playback.curr_pos,
                    paused,
                    adding_song,
                )
                stdscr.refresh()

        if next_song == -1:
            if i == scroller.pos:
                scroller.scroll_backward()
            i -= 1
        elif next_song == 1:
            if i == len(playlist) - 1:
                if loop:
                    next_next_playlist = next_playlist[:]
                    if reshuffle:
                        shuffle(next_next_playlist)
                    playlist, next_playlist = next_playlist, next_next_playlist
                    i = -1
                    scroller.pos = 0
                else:
                    # getch_manager.stop()
                    return
            else:
                if i == scroller.pos:
                    scroller.scroll_forward()
            i += 1


def print_entry(entry_list):
    """`entry_list` should be passed as a list (what you get when you call
    `line.split("|")`)."""
    click.secho(entry_list[0] + " ", fg="bright_black", nl=False)
    click.secho(entry_list[1], fg="blue", nl=(len(entry_list) == 2))
    if len(entry_list) > 2:
        click.echo(" " + ", ".join(entry_list[2].split(",")))
