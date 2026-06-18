const { createApp } = Vue;

createApp({
  data() {
    return {
      player: null,
      started: false
    };
  },

  mounted() {
    window.onYouTubeIframeAPIReady = this.initPlayer;
  },

  methods: {
    initPlayer() {
      this.player = new YT.Player("player", {
        height: "100%",
        width: "100%",
        videoId: "",
        events: {
          onReady: this.onReady,
          onStateChange: this.onStateChange
        }
      });
    },

    onReady() {
      // autoplay richiede gesto utente
    },

    async start() {
      this.started = true;
      await this.nextTrack();
    },

    async nextTrack() {
      const res = await fetch("http://localhost:8000/api/queue/next");
      const data = await res.json();

      if (data.youtube_video_id) {
        this.player.loadVideoById(data.youtube_video_id);
      }
    },

    onStateChange(event) {
      if (event.data === YT.PlayerState.ENDED) {
        this.nextTrack();
      }
    }
  }
}).mount("#app");