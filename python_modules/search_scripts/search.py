from playwright.sync_api import sync_playwright

from .block_resources import block_resources
from .azul import search_azul_viagens
from .gol import search_gol_airlines

import json

verified_flights = []

def search_flights_in_company(reserve):

    with sync_playwright() as pw:

        browser = pw.chromium.launch(headless=False)

        context = browser.new_context(reduced_motion="reduce")

        context.route("**/*", block_resources)

        
        verified_flights.append(search_azul_viagens(context, reserve))
        
        browser.close()

        print(f"\n{verified_flights} \n finalizado!!")
