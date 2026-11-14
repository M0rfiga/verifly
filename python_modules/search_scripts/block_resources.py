
def block_resources(route, request):
    blocked_types = ["image", "stylesheet", "font", "media"]

    if route.request.resource_type in blocked_types:
        route.abort()
    else:
        route.continue_()