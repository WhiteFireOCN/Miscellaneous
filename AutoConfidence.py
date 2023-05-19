def getConfidenceScore(ookla_results, cloudflare_results, ping_results, trace_ping_results, wifi_in_use, approval_condition, statistics_mapping, confidence_mapping):
    _cm = confidence_mapping  # shorten the code

    # Start us off at 100% confidence
    confidence_score = 100

    # Check if Wi-Fi was being used
    if (wifi_in_use is True):
        # Reduce the confidence score if Wi-Fi is in use
        confidence_score -= _cm["wifi-handicap"]  # _cm["wifi-handicap"] defaults to 5 in the configuration

    # Check if there is an approval requirement, such as a wireless ISP or VPN provider
    if (approval_condition is True):
        # Reduce the confidence score if there is an approval requirement
        confidence_score -= _cm["approval-handicap"]  # _cm["approval-handicap"] defaults to 20 in the configuration

    # If Wi-Fi is enabled and we were using a VPN, the confidence score would be 75 (by default) at this point

    # Initialize some variables for the Ookla tests
    ookla_download = 0
    ookla_upload = 0
    ookla_divisor = 0
    for ookla_result in ookla_results:
        # Multiply the download/upload speeds of each test by their thread count. Higher thread count will mean a higher weight in the 'average'.
        ookla_download += (ookla_result.download_bps * ookla_result.thread_count)
        ookla_upload += (ookla_result.upload_bps * ookla_result.thread_count)

        # Increment the divisor by the thread count so we're still consistent
        ookla_divisor += ookla_result.thread_count

    # Calculate the averages and then divide by 1000 to get Kbps from bps, then divide again to get Mbps from Kbps.
    weighted_ookla_download_mbps = ((ookla_download / ookla_divisor) / 1000) / 1000
    weighted_ookla_upload_mbps = ((ookla_upload / ookla_divisor) / 1000) / 1000

    # Check if the weighted download average is less than the required for this business unit
    if (weighted_ookla_download_mbps < statistics_mapping["download-mbps-red"]):
        # If so, find the distance between the "line" and our result, and reduce the confidence score by that much.
        # _cm["ookla-download-cap"] is set to 20 in the config, and this value is the max amount that can be reduced at once by this result
        confidence_score -= min(_cm["ookla-download-cap"], max(0, (abs(weighted_ookla_download_mbps - statistics_mapping["download-mbps-red"]))))

    # Check if the weighted upload average is less than the required for this business unit
    if (weighted_ookla_upload_mbps < statistics_mapping["upload-mbps-red"]):
        # Same as the download, but for the upload. The cap is still 20, but can be altered separately from the download.
        confidence_score -= min(_cm["ookla-upload-cap"], max(0, (abs(weighted_ookla_upload_mbps - statistics_mapping["upload-mbps-red"]))))

    # Initialize empty variables for the Cloudflare tests, similar to the Ookla tests.
    cloudflare_download = 0
    cloudflare_upload = 0
    cloudflare_download_divisor = 0
    cloudflare_upload_divisor = 0

    for cloudflare_result in cloudflare_results:
        # Check if the download/upload is 0Mbps, which indicates a failure
        if (cloudflare_result.download_bps == 0 or cloudflare_result.upload_bps == 0):
            # Reduce the confidence score by 10 points. All 3 failed tests will accumlate to -30 off of the final score.
            confidence_score -= 10
            continue

        # Check if the test count was 0. This indicates the particular test was skipped.
        if (cloudflare_result.test_count == 0):
            # Reduce the confidence score by 5 points. Skips only really occur if it was predicted to take too long due to slow bandwidth
            # Less significant than a failure, but not insignificant.
            confidence_score -= 5
            continue

        # Multiply the bits per second by the product of the download/upload size and test count.
        # More test counts per payload size will mean the number has a higher weight.
        # For example, 2 tests with 100MB will result in multiplying the result by 200.
        # 6 tests with 2.5MB will result in multiplying the result by 15.
        # The higher payload sizes are more significant so this works out to properly weight the final number
        cloudflare_download += (cloudflare_result.download_bps * (cloudflare_result.download_size * cloudflare_result.test_count))
        cloudflare_upload += (cloudflare_result.upload_bps * (cloudflare_result.upload_size * cloudflare_result.test_count))

        # Increment the download/upload divisors.
        # These are separate unlike the Ookla tests because the download/upload sizes per test are ALWAYS different.
        cloudflare_download_divisor += (cloudflare_result.download_size * cloudflare_result.test_count)
        cloudflare_upload_divisor += (cloudflare_result.upload_size * cloudflare_result.test_count)

    # Calculate the average, same as the Ookla tests.
    weighted_cloudflare_download_mbps = ((cloudflare_download / cloudflare_download_divisor) / 1000) / 1000
    weighted_cloudflare_upload_mbps = ((cloudflare_upload / cloudflare_upload_divisor) / 1000) / 1000

    # Perform the same calculations as the Ookla tests, reducing the confidence score by a calculated amount, relative to how 'bad' it is.
    if (weighted_cloudflare_download_mbps < statistics_mapping["download-mbps-red"]):
        confidence_score -= min(_cm["cloudflare-download-cap"], max(0, (abs(weighted_cloudflare_download_mbps - statistics_mapping["download-mbps-red"]))))

    if (weighted_cloudflare_upload_mbps < statistics_mapping["upload-mbps-red"]):
        confidence_score -= min(_cm["cloudflare-upload-cap"], max(0, (abs(weighted_cloudflare_upload_mbps - statistics_mapping["upload-mbps-red"]))))

    # Loop through all of the ping (latency) results
    for ping_result in ping_results:
        # Check if this ping result was for the local gateway/router
        if (ping_result.is_gateway):
            # Check if we're supposed to include the local gateway in the calculations (default is 'no')
            if (_cm["include-gateway"] is False):
                # If we're not supposed to include it, call 'continue' to move onto the next item
                continue

        # Check if this ping test failed
        if (ping_result.test_failed):
            # It's not terribly uncommon to see a failed ping test, so just slightly decrement the confidence score in this case, and continue on
            confidence_score -= 1
            continue

        # Perform the same calculations as the Ookla/Cloudflare tests, reducing the confidence score.
        # The difference between the result and the threshold is multiplied by a certain value to help weight each one.
        # Jitter matters more than latency, for instance, so by multiplying it by the values specified, I can tune the final number

        # Example
        # latency_multiplier = 0.07
        # average_latency = 87ms
        # threshold = 50ms
        # absolute value of 87-50 is 37
        # 0.07 * 37 = 2.59
        # Reduce the confidence score by 2.59.
        # This is done per-test, so if all 7 had the same result then we would ultimately reduce the confidence score by 7 * 2.59, just based on latency

        if (ping_result.average_latency > statistics_mapping["latency-red"]):
            confidence_score -= (_cm["latency-multiplier"] * (abs(ping_result.average_latency - statistics_mapping["latency-red"])))

        if (ping_result.jitter > statistics_mapping["jitter-red"]):
            confidence_score -= (_cm["jitter-multiplier"] * (abs(ping_result.jitter - statistics_mapping["jitter-red"])))

        loss = (ping_result.packets_lost / ping_result.packets_sent) * 100
        if (loss > statistics_mapping["packet-loss-red"]):
            confidence_score -= (_cm["loss-multiplier"] * (abs(loss - statistics_mapping["packet-loss-red"])))

    # Make sure the number is still between 0-100
    # This is pretty much an impossible case, but it's here as a backup.
    bounded_confidence_score = min(100, max(0, confidence_score))

    # Convert the decimal number into a whole integer. 86.7% -> 87%
    return round(bounded_confidence_score)
