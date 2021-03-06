# Copyright (C) 2014 LiuLang <gsushzhsosgsu@gmail.com>
# Use of this source code is governed by GPLv3 license that can be found
# in http://www.gnu.org/licenses/gpl-3.0.html

import os
import random
import sys
sys.path.insert(0, os.path.dirname(__file__))
import time

from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Notify

import Config
Config.check_first()
_ = Config._
import gutil
import util
from MimeProvider import MimeProvider
from PreferencesDialog import PreferencesDialog

from CategoryPage import *
from CloudPage import CloudPage
from DownloadPage import DownloadPage
from HomePage import HomePage
from PreferencesDialog import PreferencesDialog
from SigninDialog import SigninDialog
from TrashPage import TrashPage
from UploadPage import UploadPage

if Gtk.MAJOR_VERSION <= 3 and Gtk.MINOR_VERSION < 10:
    GObject.threads_init()
(ICON_COL, NAME_COL, TOOLTIP_COL, COLOR_COL) = list(range(4))
BLINK_DELTA = 250    # 字体闪烁间隔, 250 miliseconds 
BLINK_SUSTAINED = 3  # 字体闪烁持续时间, 5 seconds


class App:

    profile = None
    cookie = None
    tokens = None
    default_dark_color = Gdk.RGBA(0.9, 0.9, 0.9, 1)
    default_light_color = Gdk.RGBA(0.1, 0.1, 0.1, 1)
    default_color = default_dark_color
    status_icon = None

    def __init__(self):
        self.app = Gtk.Application.new(Config.DBUS_APP_NAME, 0)
        self.app.connect('startup', self.on_app_startup)
        self.app.connect('activate', self.on_app_activate)
        self.app.connect('shutdown', self.on_app_shutdown)

    def on_app_startup(self, app):
        self.icon_theme = Gtk.IconTheme.get_default()
        #self.icon_theme.append_search_path(Config.ICON_PATH)
        self.mime = MimeProvider(self)
        self.color_schema = Config.load_color_schema()
        self.set_dark_theme(True)

        self.window = Gtk.ApplicationWindow.new(application=app)
        self.window.set_default_size(*gutil.DEFAULT_PROFILE['window-size'])
        self.window.set_title(Config.APPNAME)
        self.window.props.hide_titlebar_when_maximized = True
        self.window.set_icon_name(Config.NAME)
        self.window.connect('check-resize', self.on_main_window_resized)
        self.window.connect('delete-event', self.on_main_window_deleted)
        app.add_window(self.window)

        # set drop action
        targets = [
            ['text/plain', Gtk.TargetFlags.OTHER_APP, 0],
            ['*.*', Gtk.TargetFlags.OTHER_APP, 1]]
        target_list =[Gtk.TargetEntry.new(*t) for t in targets]
        self.window.drag_dest_set(
            Gtk.DestDefaults.ALL, target_list, Gdk.DragAction.COPY)
        self.window.connect(
            'drag-data-received', self.on_main_window_drag_data_received)

        app_menu = Gio.Menu.new()
        app_menu.append(_('Preferences'), 'app.preferences')
        app_menu.append(_('Sign out'), 'app.signout')
        app_menu.append(_('About'), 'app.about')
        app_menu.append(_('Quit'), 'app.quit')
        app.set_app_menu(app_menu)

        preferences_action = Gio.SimpleAction.new('preferences', None)
        preferences_action.connect(
            'activate', self.on_preferences_action_activated)
        app.add_action(preferences_action)
        signout_action = Gio.SimpleAction.new('signout', None)
        signout_action.connect('activate', self.on_signout_action_activated)
        app.add_action(signout_action)
        about_action = Gio.SimpleAction.new('about', None)
        about_action.connect('activate', self.on_about_action_activated)
        app.add_action(about_action)
        quit_action = Gio.SimpleAction.new('quit', None)
        quit_action.connect('activate', self.on_quit_action_activated)
        app.add_action(quit_action)

        paned = Gtk.Paned()
        #paned.props.position = 15
        self.window.add(paned)

        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        paned.add1(left_box)
        paned.child_set_property(left_box, 'shrink', False)
        paned.child_set_property(left_box, 'resize', False)

        nav_window = Gtk.ScrolledWindow()
        nav_window.props.hscrollbar_policy = Gtk.PolicyType.NEVER
        left_box.pack_start(nav_window, True, True, 0)

        # icon_name, disname, tooltip, color
        self.nav_liststore = Gtk.ListStore(str, str, str, Gdk.RGBA)
        nav_treeview = Gtk.TreeView(model=self.nav_liststore)
        self.nav_selection = nav_treeview.get_selection()
        nav_treeview.props.headers_visible = False
        nav_treeview.set_tooltip_column(TOOLTIP_COL)
        icon_cell = Gtk.CellRendererPixbuf()
        icon_cell.props.xalign = 1
        icon_col = Gtk.TreeViewColumn('Icon', icon_cell, icon_name=ICON_COL)
        icon_col.props.fixed_width = 40
        nav_treeview.append_column(icon_col)
        name_cell = Gtk.CellRendererText()
        name_col = Gtk.TreeViewColumn(
                'Places', name_cell, text=NAME_COL, foreground_rgba=COLOR_COL)
        nav_treeview.append_column(name_col)
        nav_selection = nav_treeview.get_selection()
        nav_selection.connect('changed', self.on_nav_selection_changed)
        nav_window.add(nav_treeview)

        self.progressbar = Gtk.ProgressBar()
        self.progressbar.set_show_text(True)
        self.progressbar.set_text(_('Unknown'))
        left_box.pack_end(self.progressbar, False, False, 0)

        self.notebook = Gtk.Notebook()
        self.notebook.props.show_tabs = False
        paned.add2(self.notebook)

    def on_app_activate(self, app):
        self.window.show_all()
        if not self.profile:
            self.show_signin_dialog()

    def on_app_shutdown(self, app):
        '''Dump profile content to disk'''
        if self.profile:
            self.upload_page.on_destroy()
            self.download_page.on_destroy()

    def run(self, argv):
        self.app.run(argv)

    def quit(self):
        self.app.quit()

    def set_dark_theme(self, status):
        settings = Gtk.Settings.get_default()
        settings.props.gtk_application_prefer_dark_theme = status
        if status:
            self.default_color = self.default_dark_color
        else:
            self.default_color = self.default_light_color
        if self.profile:
            for row in self.nav_liststore:
                row[3] = self.default_color

    def show_signin_dialog(self, auto_signin=True):
        self.profile = None
        signin = SigninDialog(self, auto_signin=auto_signin)
        signin.run()
        signin.destroy()

        if self.profile:
            self.init_notebook()
            self.notebook.connect('switch-page', self.on_notebook_switched)
            self.init_status_icon()
            self.init_notify()
            self.set_dark_theme(self.profile['use-dark-theme'])

            if self.profile['first-run']:
                self.profile['first-run'] = False
                preferences = PreferencesDialog(self)
                preferences.run()
                preferences.destroy()
                gutil.dump_profile(self.profile)

            self.home_page.load()
            self.switch_page(self.home_page)
            return
        self.quit()

    def on_main_window_resized(self, window):
        if self.profile:
            self.profile['window-size'] = window.get_size()

    def on_main_window_deleted(self, window, event):
        if self.profile and self.profile['use-status-icon']:
            window.hide()
        else:
            self.quit()
        return True

    def on_main_window_drag_data_received(self, window, drag_context, x, y,
                                          data, info, time):
        uris = data.get_text()
        source_paths = util.uris_to_paths(uris)
        if source_paths and self.profile:
            self.upload_page.add_file_tasks(source_paths)

    def on_preferences_action_activated(self, action, params):
        if self.profile:
            dialog = PreferencesDialog(self)
            dialog.run()
            dialog.destroy()
            if self.profile:
                gutil.dump_profile(self.profile)
                if self.profile['use-status-icon'] and not self.status_icon:
                    self.init_status_icon()
                self.set_dark_theme(self.profile['use-dark-theme'])

    def on_signout_action_activated(self, action, params):
        '''在退出登录前, 应该保存当前用户的所有数据'''
        if self.profile:
            self.upload_page.pause_tasks()
            self.download_page.pause_tasks()
            self.show_signin_dialog(auto_signin=False)

    def on_about_action_activated(self, action, params):
        dialog = Gtk.AboutDialog()
        dialog.set_modal(True)
        dialog.set_transient_for(self.window)
        dialog.set_program_name(Config.APPNAME)
        dialog.set_logo_icon_name(Config.NAME)
        dialog.set_version(Config.VERSION)
        dialog.set_comments(Config.DESCRIPTION)
        dialog.set_copyright(Config.COPYRIGHT)
        dialog.set_website(Config.HOMEPAGE)
        dialog.set_license_type(Gtk.License.GPL_3_0)
        dialog.set_authors(Config.AUTHORS)
        dialog.run()
        dialog.destroy()

    def on_quit_action_activated(self, action, params):
        self.quit()

    def update_quota(self, quota_info, error=None):
        '''更新网盘容量信息'''
        if not quota_info or quota_info['errno'] != 0:
            return
        used = quota_info['used']
        total = quota_info['total']
        used_size = util.get_human_size(used)[0]
        total_size = util.get_human_size(total)[0]
        self.progressbar.set_text(used_size + ' / ' + total_size)
        self.progressbar.set_fraction(used / total)

    def init_notebook(self):
        def append_page(page):
            self.notebook.append_page(page, Gtk.Label.new(page.disname))
            self.nav_liststore.append([
                page.icon_name, page.disname,
                page.tooltip, self.default_color,
                ])

        self.default_color = self.get_default_color()
        self.nav_liststore.clear()
        children = self.notebook.get_children()
        for child in children:
            self.notebook.remove(child)

        self.home_page = HomePage(self)
        append_page(self.home_page)
        self.picture_page = PicturePage(self)
        append_page(self.picture_page)
        self.doc_page = DocPage(self)
        append_page(self.doc_page)
        self.video_page = VideoPage(self)
        append_page(self.video_page)
        self.bt_page = BTPage(self)
        append_page(self.bt_page)
        self.music_page = MusicPage(self)
        append_page(self.music_page)
        self.other_page = OtherPage(self)
        append_page(self.other_page)
        self.trash_page = TrashPage(self)
        append_page(self.trash_page)
        self.cloud_page = CloudPage(self)
        append_page(self.cloud_page)
        self.download_page = DownloadPage(self)
        append_page(self.download_page)
        self.upload_page = UploadPage(self)
        append_page(self.upload_page)

        self.notebook.show_all()

    def reload_current_page(self, *args, **kwds):
        '''重新载入当前页面.
        
        所有的页面都应该实现reload()方法.
        '''
        index = self.notebook.get_current_page()
        self.notebook.get_nth_page(index).reload()

    def switch_page_by_index(self, index):
        self.notebook.set_current_page(index)

    def switch_page(self, page):
        for index, p in enumerate(self.notebook):
            if p == page:
                self.nav_selection.select_iter(self.nav_liststore[index].iter)
                #self.notebook.set_current_page(index)
                break

    def on_notebook_switched(self, notebook, page, index):
        if page.first_run:
            page.first_run = False
            page.load()

    def on_nav_selection_changed(self, nav_selection):
        model, iter_ = nav_selection.get_selected()
        if not iter_:
            return
        path = model.get_path(iter_)
        index = path.get_indices()[0]
        self.switch_page_by_index(index)

    def init_status_icon(self):
        if (self.profile and self.profile['use-status-icon'] and
                not self.status_icon):
            self.status_icon = Gtk.StatusIcon()
            self.status_icon.set_from_icon_name(Config.NAME)
            # left click
            self.status_icon.connect(
                    'activate', self.on_status_icon_activate)
            # right click
            self.status_icon.connect(
                    'popup_menu', self.on_status_icon_popup_menu)
        else:
            self.status_icon = None

    def on_status_icon_activate(self, status_icon):
        if self.window.props.visible:
            self.window.hide()
        else:
            self.window.present()

    def on_status_icon_popup_menu(self, status_icon, event_button,
                                event_time):
        menu = Gtk.Menu()
        show_item = Gtk.MenuItem.new_with_label(_('Show App'))
        show_item.connect('activate', self.on_status_icon_show_app_activate)
        menu.append(show_item)

        sep_item = Gtk.SeparatorMenuItem()
        menu.append(sep_item)

        pause_upload_item = Gtk.MenuItem.new_with_label(
                _('Pause Uploading Tasks'))
        pause_upload_item.connect(
                'activate', lambda *args: self.upload_page.pause_tasks())
        menu.append(pause_upload_item)

        pause_download_item = Gtk.MenuItem.new_with_label(
                _('Pause Downloading Tasks'))
        pause_download_item.connect(
                'activate', lambda *args: self.download_page.pause_tasks())
        menu.append(pause_download_item)

        sep_item = Gtk.SeparatorMenuItem()
        menu.append(sep_item)

        quit_item = Gtk.MenuItem.new_with_label(_('Quit'))
        quit_item.connect('activate', self.on_status_icon_quit_activate)
        menu.append(quit_item)

        menu.show_all()
        menu.popup(None, None,
                lambda a,b: Gtk.StatusIcon.position_menu(menu, status_icon),
                None, event_button, event_time)

    def on_status_icon_show_app_activate(self, menuitem):
        self.window.present()

    def on_status_icon_quit_activate(self, menuitem):
        self.quit()

    # Open API
    def blink_page(self, page):
        def blink():
            row[COLOR_COL] = random.choice(self.color_schema)
            if time.time() - start_time > BLINK_SUSTAINED:
                row[COLOR_COL] = self.default_color
                return False
            return True
        
        start_time = time.time()
        for index, p in enumerate(self.notebook):
            if p == page:
                break
        row = self.nav_liststore[index]
        GLib.timeout_add(BLINK_DELTA, blink)

    def get_default_color(self):
        context = self.window.get_style_context()
        return context.get_color(Gtk.StateFlags.NORMAL)

    # Open API
    def update_clipboard(self, text):
        '''将文本复制到系统剪贴板里面'''
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, -1)
        self.toast(_('{0} copied to clipboard'.format(text)))

    def init_notify(self):
        self.notify = None
        if self.profile['use-notify']:
            status = Notify.init(Config.APPNAME)
            if not status:
                return
            self.notify = Notify.Notification.new(
                    Config.APPNAME, '', Config.NAME)

    # Open API
    def toast(self, text):
        '''在用户界面显示一个消息通知.

        可以使用系统提供的Notification工具, 也可以在窗口的最下方滚动弹出
        这个消息
        '''
        if self.notify:
            self.notify.update(Config.APPNAME, text, Config.NAME)
            self.notify.show()
