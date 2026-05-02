import math
import torch
import torch.nn as nn


class PositionalEncoding(nn.Module):
    """Sinusoidal Positional Encoding (Attention Is All You Need)."""

    def __init__(self, d_model, max_len=200):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len).unsqueeze(1).float()
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float() * -(math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer("pe", pe.unsqueeze(0))  # [1, max_len, d_model]

    def forward(self, x):
        """x: [B, T, d_model]"""
        return x + self.pe[:, : x.size(1), :]


class TransformerAutoencoder(nn.Module):
    def __init__(
        self, service_vocab, op_vocab, status_vocab=6,
        app_vocab=2, metrics_feature_num=1
    ):
        super().__init__()

        # --- Embedding dims (giữ nguyên GRU) ---
        self.service_embed_dim = 4
        self.op_embed_dim = 6
        self.status_embed_dim = 2
        self.app_embed_dim = 2
        self.latent_dim = 32
        self.d_model = 64

        self.context_dim = (
            2 * self.service_embed_dim
            + 2 * self.op_embed_dim
            + self.status_embed_dim
            + self.app_embed_dim
        )

        # --- Embedding layers (giữ nguyên GRU) ---
        self.service_embedding = nn.Embedding(service_vocab, self.service_embed_dim)
        self.op_embedding = nn.Embedding(op_vocab, self.op_embed_dim)
        self.status_embedding = nn.Embedding(status_vocab, self.status_embed_dim)
        self.app_embedding = nn.Embedding(app_vocab, self.app_embed_dim)

        # --- Positional Encoding ---
        self.pos_encoder = PositionalEncoding(self.d_model)

        # --- Encoder ---
        self.input_projection = nn.Linear(
            self.context_dim + metrics_feature_num, self.d_model
        )  # 22 → 64

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=self.d_model,
            nhead=4,
            dim_feedforward=128,
            dropout=0.1,
            batch_first=True,
        )
        self.transformer_encoder = nn.TransformerEncoder(
            encoder_layer, num_layers=2
        )

        self.encoder_norm = nn.LayerNorm(self.d_model)
        self.to_latent = nn.Linear(self.d_model, self.latent_dim)  # 64 → 32

        # --- Decoder (dùng TransformerEncoder, KHÔNG TransformerDecoder) ---
        self.from_latent = nn.Linear(self.latent_dim, self.d_model)  # 32 → 64

        self.decoder_input_projection = nn.Linear(
            self.d_model + self.context_dim, self.d_model
        )  # 85 → 64

        decoder_layer = nn.TransformerEncoderLayer(
            d_model=self.d_model,
            nhead=4,
            dim_feedforward=128,
            dropout=0.1,
            batch_first=True,
        )
        self.transformer_decoder = nn.TransformerEncoder(
            decoder_layer, num_layers=2
        )

        self.fc_out = nn.Linear(self.d_model, metrics_feature_num)  # 64 → 1

    def forward(self, service_id, parent_service_id, op_id, parent_op_id, http_status, app_id, metrics_x):
        """
        service_id, parent_service_id, op_id, parent_op_id, http_status, app_id: [B]
        metrics_x: [B, T, F]
        """
        batch_size, seq_length, _ = metrics_x.shape

        # ---- context embedding (giữ nguyên GRU) ----
        service_emb = self.service_embedding(service_id).unsqueeze(1).expand(batch_size, seq_length, -1)
        parent_service_emb = self.service_embedding(parent_service_id).unsqueeze(1).expand(batch_size, seq_length, -1)
        op_emb = self.op_embedding(op_id).unsqueeze(1).expand(batch_size, seq_length, -1)
        parent_op_emb = self.op_embedding(parent_op_id).unsqueeze(1).expand(batch_size, seq_length, -1)
        status_emb = self.status_embedding(http_status).unsqueeze(1).expand(batch_size, seq_length, -1)
        app_emb = self.app_embedding(app_id).unsqueeze(1).expand(batch_size, seq_length, -1)

        context = torch.cat([
            service_emb, parent_service_emb,
            op_emb, parent_op_emb,
            status_emb,
            app_emb
        ], dim=-1)  # [B, T, context_dim]

        # ---- encoder ----
        enc_input = torch.cat([metrics_x, context], dim=-1)    # [B, T, 22]
        enc_proj = self.input_projection(enc_input)             # [B, T, 64]
        enc_proj = self.pos_encoder(enc_proj)                   # + positional encoding
        enc_out = self.transformer_encoder(enc_proj)            # [B, T, 64]

        h_pooled = enc_out.mean(dim=1)                          # [B, 64]
        h_pooled = self.encoder_norm(h_pooled)
        z = self.to_latent(h_pooled)                            # [B, 32]  BOTTLENECK

        # ---- decoder (NO cross-attention to enc_out) ----
        z_exp = self.from_latent(z)                             # [B, 64]
        z_exp = z_exp.unsqueeze(1).expand(batch_size, seq_length, -1)  # [B, T, 64]
        dec_input = torch.cat([z_exp, context], dim=-1)         # [B, T, 85]
        dec_proj = self.decoder_input_projection(dec_input)     # [B, T, 64]
        dec_proj = self.pos_encoder(dec_proj)                   # + positional encoding
        dec_out = self.transformer_decoder(dec_proj)            # [B, T, 64]

        recon = self.fc_out(dec_out)                            # [B, T, 1]
        return recon
