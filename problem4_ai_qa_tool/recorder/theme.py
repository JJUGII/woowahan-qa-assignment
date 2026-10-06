"""Shared mint palette for the dashboard and review/settings controls."""
import customtkinter as ctk

BG = '#F3F8F8'
CARD = '#FFFFFF'
BORDER = '#DCE8E8'
TEXT = '#173A3B'
MUTED = '#647B7B'
MINT = '#2AC1BC'
MINT_HOVER = '#22ADA8'
SOFT = '#E7F8F6'
SIDEBAR = '#163F40'
FONT = ('맑은 고딕', 13)
TITLE = ('맑은 고딕', 17, 'bold')


def apply_theme():
    ctk.set_appearance_mode('light')
    ctk.set_default_color_theme('blue')
    theme = ctk.ThemeManager.theme
    for kind in ('CTkButton', 'CTkOptionMenu', 'CTkCheckBox', 'CTkRadioButton', 'CTkSwitch', 'CTkSlider'):
        theme[kind]['fg_color'] = [MINT, MINT]
        if 'hover_color' in theme[kind]:
            theme[kind]['hover_color'] = [MINT_HOVER, MINT_HOVER]
    theme['CTkButton']['text_color'] = [TEXT, TEXT]
    theme['CTkOptionMenu'].update(text_color=[TEXT, TEXT], button_color=[MINT_HOVER, MINT_HOVER],
                                 button_hover_color=[MINT, MINT])
    theme['CTkSegmentedButton'].update(selected_color=[MINT, MINT], selected_hover_color=[MINT_HOVER, MINT_HOVER],
                                      text_color=[TEXT, TEXT])
    theme['CTkSwitch']['progress_color'] = [MINT, MINT]
    theme['CTkEntry'].update(border_color=[BORDER, BORDER], fg_color=[CARD, CARD], text_color=[TEXT, TEXT])
    theme['CTkLabel']['text_color'] = [TEXT, TEXT]
