MAX_ATTEMPTS = 6
STOP = MAX_ATTEMPTS - 1

def search_azul_viagens(context, reserve):

    for attempts in range(1, MAX_ATTEMPTS, 1):
    
        try:
            context.clear_cookies()

            page = context.new_page()

            page.goto(
                reserve, 
                wait_until="domcontentloaded"
            )

            accept_cookies = page.locator('#onetrust-accept-btn-handler')

            if accept_cookies.is_visible():
                accept_cookies.click()

            flights_info_in_company = page.locator("div.regular")

            quantity_flights = flights_info_in_company.locator(":scope > div").count()



    
            if quantity_flights > 1: #Verificando reservas com trecho de ida e volta

                flights_in_company = {
                    "locator": page.locator(".container__reservation__text__code").text_content(),

                    "outbound_flight_infos": {
                        "origin": {
                            "airport": flights_info_in_company.locator("p").nth(0).text_content(),
                            "date": flights_info_in_company.locator("p").locator('time').nth(1).text_content(),
                            "hour": flights_info_in_company.locator("p").locator('time').nth(0).text_content()
                        },

                        "destiny": {
                            "airport": flights_info_in_company.locator("p").nth(4).text_content(),
                            "date": flights_info_in_company.locator("p").locator('time').nth(2).text_content(),
                            "hour": flights_info_in_company.locator("p").locator('time').nth(3).text_content()
                        }
                    },

                    "return_flight_infos": {
                        "origin": {
                            "airport": flights_info_in_company.locator("p").nth(4).text_content(),
                            "date": flights_info_in_company.locator("p").locator('time').nth(4).text_content(),
                            "hour": flights_info_in_company.locator("p").locator('time').nth(5).text_content()
                        },

                        "destiny": {
                            "airport": flights_info_in_company.locator("p").nth(11).text_content(),
                            "date": flights_info_in_company.locator("p").locator('time').nth(5).text_content(),
                            "hour": flights_info_in_company.locator("p").locator('time').nth(6).text_content()
                        }
                    }
                }
                

            else: #Verificação reservas com apenas o trecho de ida

                flights_in_company = {
                    "locator": page.locator(".container__reservation__text__code").text_content(),

                    "outbound_flight_infos": {
                        "origin": {
                            "airport": flights_info_in_company.locator("p").nth(0).text_content(),
                            "date": flights_info_in_company.locator("p").locator('time').nth(1).text_content(),
                            "hour": flights_info_in_company.locator("p").locator('time').nth(0).text_content()
                        },

                        "destiny": {
                            "airport": flights_info_in_company.locator("p").nth(4).text_content(),
                            "date": flights_info_in_company.locator("p").locator('time').nth(2).text_content(),
                            "hour": flights_info_in_company.locator("p").locator('time').nth(3).text_content()
                        }
                    }
                }



        
            page.close()

            return flights_in_company
            
        except Exception as error:  

            print(f"\n\n{error}\nAcessando novamente...")

            if attempts == STOP: #Verifica se já ocorreram 5 tentativas

                flights_in_company = {
                    "locator": None,

                    "outbound_flight_infos": {
                        "origin": {
                            "airport": None,
                            "date": None,
                            "hour": None
                        },

                        "destiny": {
                            "airport": None,
                            "date": None,
                            "hour": None
                        }
                    },

                    "return_flight_infos": {
                        "origin": {
                            "airport": None,
                            "date": None,
                            "hour": None
                        },

                        "destiny": {
                            "airport": None,
                            "date": None,
                            "hour": None
                        }
                    }
                }
              
                page.close()
                
                return flights_in_company

            page.close()

            continue
