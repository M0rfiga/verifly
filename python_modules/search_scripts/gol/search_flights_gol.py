MAX_ATTEMPTS = 2
STOP = MAX_ATTEMPTS - 1

def search_gol_airlines(index_reserve, context, reserve):

    for attempts in range(1, MAX_ATTEMPTS, 1):
    
        try:
            context.clear_cookies()

            page = context.new_page()

            page.goto(
                reserve, 
                wait_until="domcontentloaded"
            )

            accept_cookies = page.locator('#onetrust-accept-btn-handler')

            close_modal = page.locator('#btn_closemodal')



            if accept_cookies.is_visible():
                accept_cookies.click()

            if close_modal.is_visible():
                close_modal.click()



            if page.wait_for_selector(".m-home-flight-card__container", timeout=100000).is_visible() == True:     

                flights_info_in_company = page.locator(".m-home-flight-card__container")

                quantity_flights = flights_info_in_company.locator(":scope > div").count()

                if quantity_flights > 1:

                    outbound_flight_infos = flights_info_in_company.locator("#itinenary-0")
                    return_flight_infos = flights_info_in_company.locator("#itinenary-1")

                    flights_in_company = {
                        "locator": page.locator(".home-header__code--value").text_content(),

                        "outbound_flight_infos": {
                            "origin": {
                                "airport": outbound_flight_infos.locator(".m-home-flight-card__segment-code").nth(0).text_content(),
                                "date": outbound_flight_infos.locator(".m-home-flight-card__segment-date").nth(0).text_content(),
                                "hour": outbound_flight_infos.locator(".m-home-flight-card__segment-hour").nth(0).text_content()
                            },

                            "destiny": {
                                "airport": outbound_flight_infos.locator(".m-home-flight-card__segment-code").nth(1).text_content(),
                                "date": outbound_flight_infos.locator(".m-home-flight-card__segment-date").nth(1).text_content(),
                                "hour": outbound_flight_infos.locator(".m-home-flight-card__segment-hour").nth(1).text_content()
                            }
                        },

                        "return_flight_infos": {
                            "origin": {
                                "airport": return_flight_infos.locator(".m-home-flight-card__segment-code").nth(0).text_content(),
                                "date": return_flight_infos.locator(".m-home-flight-card__segment-date").nth(0).text_content(),
                                "hour": return_flight_infos.locator(".m-home-flight-card__segment-hour").nth(0).text_content()
                            },

                            "destiny": {
                                "airport": return_flight_infos.locator(".m-home-flight-card__segment-code").nth(1).text_content(),
                                "date": return_flight_infos.locator(".m-home-flight-card__segment-date").nth(1).text_content(),
                                "hour": return_flight_infos.locator(".m-home-flight-card__segment-hour").nth(1).text_content()
                            }
                        }
                    }
                    

                else: 

                    outbound_flight_infos = flights_info_in_company.locator("#itinenary-0")

                    flights_in_company = {
                        "locator": page.locator("span.home-header__code--value").text_content(),

                        "outbound_flight_infos": {
                            "origin": {
                                "airport": outbound_flight_infos.locator(".m-home-flight-card__segment-code").nth(0).text_content(),
                                "date": outbound_flight_infos.locator(".m-home-flight-card__segment-date").nth(0).text_content(),
                                "hour": outbound_flight_infos.locator(".m-home-flight-card__segment-hour").nth(0).text_content()
                            },

                            "destiny": {
                                "airport": outbound_flight_infos.locator(".m-home-flight-card__segment-code").nth(1).text_content(),
                                "date": outbound_flight_infos.locator(".m-home-flight-card__segment-date").nth(1).text_content(),
                                "hour": outbound_flight_infos.locator(".m-home-flight-card__segment-hour").nth(1).text_content()
                            }
                        }
                    }

            else:

                page.close()

                print("VERIFICAR RESERVA DA GOL")

                page.close()

                continue


            print("até aqui foi", quantity_flights)

            print(f"{index_reserve} - {flights_in_company["locator"]}")
            
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
