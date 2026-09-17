package com.iptvmonitor.player

import android.app.Application
import coil.ImageLoader
import coil.ImageLoaderFactory
import com.iptvmonitor.player.data.HttpClients

class PortalApp : Application(), ImageLoaderFactory {
    override fun newImageLoader(): ImageLoader {
        return ImageLoader.Builder(this)
            .okHttpClient { HttpClients.shared }
            .crossfade(true)
            .build()
    }
}
