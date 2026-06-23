const { createApp } = Vue;

createApp({
  data() {
    return {
      player: null,
      started: false,
      pendingWinner: null,
      winnerPollIntervalId: null
    };
  },

  mounted() {
    window.onYouTubeIframeAPIReady = this.initPlayer.bind(this);
    // Poll backend for poll winner (only) every 5s; when found, play it once.
    this.winnerPollIntervalId = setInterval(this.checkForWinner.bind(this), 5000);
  },

  beforeUnmount() {
    if (this.winnerPollIntervalId) {
      clearInterval(this.winnerPollIntervalId);
    }
  },

  methods: {
    initPlayer() {
      this.player = new YT.Player("player", {
        height: "100%",
        width: "100%",
        videoId: "",
        playerVars: {
          playsinline: 1
        },
        events: {
          onReady: (e) => this.onReady(e),
          onStateChange: (e) => this.onStateChange(e)
        }
      });
    },

    onReady() {
      // If a winner was found before the player was ready, play it now.
      if (this.pendingWinner && this.player) {
        // Mute first to allow autoplay in kiosk environments, then play.
        try { this.player.mute(); } catch (e) {}
        this.player.loadVideoById(this.pendingWinner);
        try { this.player.playVideo(); } catch (e) {}
        this.pendingWinner = null;
        this.started = true;
      }
      // Also check immediately for a winner on ready (don't wait for the 5s tick)
      this.checkForWinner();
    },

    async start() {
      this.started = true;
      // For kiosk we do not autoplay a random next track.
      // Instead, check for a Slack poll winner and play it if present.
      await this.checkForWinner();
    },

    async nextTrack() {
      const res = await fetch("/api/queue/next");
      if (!res.ok) {
        console.warn("nextTrack: API returned", res.status);
        return;
      }

      const data = await res.json();

      if (data && data.youtube_video_id) {
        this.player.loadVideoById(data.youtube_video_id);
      } else {
        console.warn("nextTrack: no video returned", data);
      }
    },

    async checkForWinner() {
      try {
        const res = await fetch("/api/queue/winner");
        if (!res.ok) return;

        const data = await res.json();
        if (data && data.youtube_video_id) {
          // If player is ready, load immediately; otherwise keep as pending
          if (this.player && typeof this.player.loadVideoById === "function") {
            this.started = true;
            try { this.player.mute(); } catch (e) {}
            this.player.loadVideoById(data.youtube_video_id);
            try { this.player.playVideo(); } catch (e) {}
          } else {
            this.pendingWinner = data.youtube_video_id;
          }
        }
      } catch (e) {
        console.warn("checkForWinner error", e);
      }
    },

    onStateChange(event) {
      if (event.data === YT.PlayerState.ENDED) {
        // Do not play a random track when the current one ends.
        // Ask the backend for the next winner (if any) and play it.
        this.checkForWinner();
      }
    }
  }
}).mount("#app");