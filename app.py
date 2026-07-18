import customtkinter as ctk
from tkinter import filedialog, messagebox
import os
import json
from datetime import date
import shutil
import threading
import time
import psutil
import platform
import subprocess
import rawpy
import imageio
import concurrent.futures
from PIL import Image, ImageOps, ImageFilter, ImageEnhance  # ← adicione ImageFilter, ImageEnhance
import numpy as np  # ← adicione esta linha
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    GOOGLE_DRIVE_DISPONIVEL = True
except ImportError:
    GOOGLE_DRIVE_DISPONIVEL = False


# Configurações de tema do CustomTkinter
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class RevisorFotosWindow(ctk.CTkToplevel):
    def __init__(self, parent, arquivos, pasta_destino):
        super().__init__(parent)
        self.parent = parent
        self.arquivos_originais = arquivos.copy() # Lista imutável original
        self.arquivos = arquivos.copy()           # Lista ativa de fotos sendo revisadas
        self.descartados = []                     # Pilha de fotos descartadas (para Desfazer)
        self.pasta_destino = pasta_destino
        
        self.current_index = 0
        
        self.title("Revisar e Selecionar Fotos")
        self.geometry("1100x750")
        self.minsize(800, 600)
        
        # Garante foco e captura de eventos na janela de revisão
        self.focus_force()
        self.after(100, lambda: self.grab_set() if self.winfo_exists() else None)
        self.after(200, self.focus_force)
        
        # Maximiza a janela após carregar para visualização otimizada
        self.after(150, self.maximizar_janela)
        
        # Caching thread-safe para imagens
        self.cache_imagens = {} # caminho -> PIL.Image
        self.lock_cache = threading.Lock()
        
        self.setup_ui()
        self.bind_events()
        
        # Inicia a thread de pré-carregamento em segundo plano (otimização máxima)
        self.threading_preload = threading.Thread(target=self.preload_loop, daemon=True)
        self.threading_preload.start()
        
        # Exibe a primeira foto
        self.exibir_foto_atual()

    def maximizar_janela(self):
        try:
            if platform.system() == "Windows":
                self.state("zoomed")
            else:
                self.attributes("-zoomed", True)
        except Exception:
            pass

    def setup_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        # Container principal
        self.main_container = ctk.CTkFrame(self)
        self.main_container.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)
        
        self.main_container.grid_rowconfigure(0, weight=1) # Área da foto
        self.main_container.grid_rowconfigure(1, weight=0) # Barra de ferramentas e status
        self.main_container.grid_columnconfigure(0, weight=1)
        
        # Área de exibição de foto (fundo escuro para destacar a foto)
        self.frame_foto = ctk.CTkFrame(self.main_container, fg_color="#0d0d0d")
        self.frame_foto.grid(row=0, column=0, sticky="nsew", padx=15, pady=(15, 10))
        
        self.lbl_foto = ctk.CTkLabel(self.frame_foto, text="Carregando imagem...", font=ctk.CTkFont(size=16), text_color="gray")
        self.lbl_foto.pack(fill="both", expand=True)
        
        # Evento de redimensionamento dinâmico (com debounce automático)
        self.frame_foto.bind("<Configure>", self.ao_redimensionar)
        
        # Barra de ferramentas na parte inferior
        self.frame_controles = ctk.CTkFrame(self.main_container, height=80)
        self.frame_controles.grid(row=1, column=0, sticky="ew", padx=15, pady=(5, 15))
        
        self.frame_controles.grid_rowconfigure(0, weight=1)
        for i in range(6):
            self.frame_controles.grid_columnconfigure(i, weight=1)
            
        # 1. Botão Anterior
        self.btn_anterior = ctk.CTkButton(
            self.frame_controles, 
            text="◀ Anterior (Seta Esquerda)", 
            font=ctk.CTkFont(size=13),
            command=self.foto_anterior
        )
        self.btn_anterior.grid(row=0, column=0, padx=8, pady=12, sticky="ew")
        
        # 2. Botão Desfazer
        self.btn_desfazer = ctk.CTkButton(
            self.frame_controles, 
            text="↩️ Desfazer (Ctrl+Z)", 
            fg_color="#34495e", 
            hover_color="#2c3e50",
            state="disabled",
            font=ctk.CTkFont(size=13),
            command=self.desfazer_descarte
        )
        self.btn_desfazer.grid(row=0, column=1, padx=8, pady=12, sticky="ew")
        
        # 3. Botão Apagar/Descartar (Vermelho em destaque)
        self.btn_descartar = ctk.CTkButton(
            self.frame_controles, 
            text="🗑️ Apagar Foto (Delete)", 
            fg_color="#e74c3c", 
            hover_color="#c0392b",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.descartar_foto
        )
        self.btn_descartar.grid(row=0, column=2, padx=8, pady=12, sticky="ew")
        
        # 4. Botão Próxima
        self.btn_proxima = ctk.CTkButton(
            self.frame_controles, 
            text="Próxima ▶ (Seta Direita)", 
            font=ctk.CTkFont(size=13),
            command=self.proxima_foto
        )
        self.btn_proxima.grid(row=0, column=3, padx=8, pady=12, sticky="ew")
        
        # 5. Label de Status da Revisão
        self.lbl_revisao_status = ctk.CTkLabel(
            self.frame_controles, 
            text="Foto 0/0", 
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#3498db"
        )
        self.lbl_revisao_status.grid(row=0, column=4, padx=8, pady=12)
        
        # 6. Botão Finalizar (Verde em destaque)
        self.btn_finalizar = ctk.CTkButton(
            self.frame_controles, 
            text="💾 Finalizar Seleção", 
            fg_color="#2ecc71", 
            hover_color="#27ae60",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.finalizar_revisao
        )
        self.btn_finalizar.grid(row=0, column=5, padx=8, pady=12, sticky="ew")

    def bind_events(self):
        # Vincula os atalhos recursivamente em todos os widgets (garante 100% de funcionamento independente de onde está o foco)
        self.bind_keys_recursive(self)
        self.protocol("WM_DELETE_WINDOW", self.ao_fechar_janela)

    def bind_keys_recursive(self, widget):
        widget.bind("<Left>", lambda e: self.foto_anterior())
        widget.bind("<Right>", lambda e: self.proxima_foto())
        widget.bind("<Delete>", lambda e: self.descartar_foto())
        widget.bind("<BackSpace>", lambda e: self.descartar_foto())
        widget.bind("<Control-z>", lambda e: self.desfazer_descarte())
        widget.bind("<Control-Z>", lambda e: self.desfazer_descarte())
        
        for child in widget.winfo_children():
            self.bind_keys_recursive(child)

    def limpar_eventos_globais(self):
        pass

    def preload_loop(self):
        """Thread de pré-carregamento contínuo em segundo plano para suavidade total ao alternar fotos."""
        while True:
            if not self.arquivos:
                time.sleep(0.5)
                continue
                
            idx_atual = self.current_index
            paths_to_load = []
            
            # Prioridade de pré-carregamento: Atual, Próxima, Anterior, Duas à frente
            if idx_atual < len(self.arquivos):
                paths_to_load.append(self.arquivos[idx_atual])
            if idx_atual + 1 < len(self.arquivos):
                paths_to_load.append(self.arquivos[idx_atual + 1])
            if idx_atual - 1 >= 0:
                paths_to_load.append(self.arquivos[idx_atual - 1])
            if idx_atual + 2 < len(self.arquivos):
                paths_to_load.append(self.arquivos[idx_atual + 2])
                
            for path in paths_to_load:
                with self.lock_cache:
                    in_cache = path in self.cache_imagens
                
                if not in_cache:
                    try:
                        ext = os.path.splitext(path)[1].lower()
                        if ext in ['.cr2', '.nef', '.arw', '.cr3']:
                            with rawpy.imread(path) as raw:
                                # half_size=True é 4 vezes mais rápido e perfeito para renderizar na tela
                                rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=True)
                                img_pil = Image.fromarray(rgb)
                        else:
                            img_pil = Image.open(path)
                            img_pil = ImageOps.exif_transpose(img_pil)
                            img_pil.load() # Força a decodificação em segundo plano
                            
                        with self.lock_cache:
                            # Mantém o cache compacto (limite de 12 imagens) para evitar consumo excessivo de RAM
                            if len(self.cache_imagens) > 12:
                                for cached_path in list(self.cache_imagens.keys()):
                                    if cached_path not in self.arquivos:
                                        self.cache_imagens.pop(cached_path, None)
                                    else:
                                        try:
                                            distancia = abs(self.arquivos.index(cached_path) - idx_atual)
                                            if distancia > 4:
                                                self.cache_imagens.pop(cached_path, None)
                                        except ValueError:
                                            self.cache_imagens.pop(cached_path, None)
                                            
                            self.cache_imagens[path] = img_pil
                    except Exception as e:
                        print(f"Erro ao pré-carregar {path}: {e}")
                        
            time.sleep(0.1)

    def obter_imagem_pil(self, path):
        with self.lock_cache:
            if path in self.cache_imagens:
                return self.cache_imagens[path]
                
        # Fallback síncrono caso a thread ainda não tenha carregado
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext in ['.cr2', '.nef', '.arw', '.cr3']:
                with rawpy.imread(path) as raw:
                    rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=True)
                    img_pil = Image.fromarray(rgb)
            else:
                img_pil = Image.open(path)
                img_pil = ImageOps.exif_transpose(img_pil)
                img_pil.load()
            
            with self.lock_cache:
                self.cache_imagens[path] = img_pil
            return img_pil
        except Exception as e:
            print(f"Erro ao carregar imagem: {e}")
            return None

    def redimensionar_para_caber(self, img_pil, largura_alvo, altura_alvo):
        if largura_alvo <= 10 or altura_alvo <= 10:
            return None
            
        largura_orig, altura_orig = img_pil.size
        ratio = min(largura_alvo / largura_orig, altura_alvo / altura_orig)
        
        nova_largura = int(largura_orig * ratio)
        nova_altura = int(altura_orig * ratio)
        
        if nova_largura <= 0 or nova_altura <= 0:
            return None
            
        # Otimizado com HAMMING para velocidade e excelente nitidez
        try:
            from PIL.Image import Resampling
            resample_mode = Resampling.HAMMING
        except ImportError:
            resample_mode = Image.ANTIALIAS if hasattr(Image, "ANTIALIAS") else 2
            
        return img_pil.resize((nova_largura, nova_altura), resample_mode)

    def exibir_foto_atual(self):
        if not self.arquivos:
            self.lbl_foto.configure(image=None, text="Nenhuma foto para exibir.\n\nTodas as fotos foram descartadas ou revisadas!\nClique em 'Finalizar Seleção' para salvar.", font=ctk.CTkFont(size=16))
            self.lbl_revisao_status.configure(text="0 de 0")
            self.btn_descartar.configure(state="disabled")
            self.btn_proxima.configure(state="disabled")
            self.btn_anterior.configure(state="disabled")
            return
            
        if self.current_index >= len(self.arquivos):
            self.current_index = len(self.arquivos) - 1
        if self.current_index < 0:
            self.current_index = 0
            
        path_atual = self.arquivos[self.current_index]
        nome_arquivo = os.path.basename(path_atual)
        
        self.lbl_revisao_status.configure(text=f"Foto {self.current_index + 1}/{len(self.arquivos)}\n{nome_arquivo}")
        
        self.btn_anterior.configure(state="normal" if self.current_index > 0 else "disabled")
        self.btn_proxima.configure(state="normal" if self.current_index < len(self.arquivos) - 1 else "disabled")
        self.btn_descartar.configure(state="normal")
        self.btn_desfazer.configure(state="normal" if self.descartados else "disabled")
        
        self.atualizar_canvas_imagem()

    def ao_redimensionar(self, event):
        """Usa debounce de 50ms para evitar travamento da UI ao arrastar a janela."""
        if hasattr(self, "_resize_after_id"):
            self.after_cancel(self._resize_after_id)
        self._resize_after_id = self.after(50, self.atualizar_canvas_imagem)

    def atualizar_canvas_imagem(self):
        if not self.arquivos or self.current_index >= len(self.arquivos):
            return
            
        path_atual = self.arquivos[self.current_index]
        img_pil = self.obter_imagem_pil(path_atual)
        
        if not img_pil:
            self.lbl_foto.configure(image=None, text="Erro ao exibir imagem.")
            return
            
        largura_alvo = self.frame_foto.winfo_width()
        altura_alvo = self.frame_foto.winfo_height()
        
        # Garante valores padrões se a janela não tiver sido renderizada ainda
        if largura_alvo <= 10: largura_alvo = 900
        if altura_alvo <= 10: altura_alvo = 600
        
        img_scaled = self.redimensionar_para_caber(img_pil, largura_alvo - 20, altura_alvo - 20)
        
        if img_scaled:
            self.ctk_img = ctk.CTkImage(
                light_image=img_scaled, 
                dark_image=img_scaled, 
                size=(img_scaled.width, img_scaled.height)
            )
            self.lbl_foto.configure(image=self.ctk_img, text="")

    def foto_anterior(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.exibir_foto_atual()

    def proxima_foto(self):
        if self.current_index < len(self.arquivos) - 1:
            self.current_index += 1
            self.exibir_foto_atual()

    def descartar_foto(self):
        if not self.arquivos:
            return
            
        path_atual = self.arquivos[self.current_index]
        self.arquivos.remove(path_atual)
        self.descartados.append(path_atual)
        
        self.btn_desfazer.configure(state="normal")
        
        if not self.arquivos:
            self.exibir_foto_atual()
            return
            
        if self.current_index >= len(self.arquivos):
            self.current_index = len(self.arquivos) - 1
            
        self.exibir_foto_atual()

    def desfazer_descarte(self):
        if not self.descartados:
            return
            
        recovered_path = self.descartados.pop()
        
        # Encontra a posição original relativa na lista
        orig_idx = self.arquivos_originais.index(recovered_path)
        
        insert_idx = 0
        for i, active_path in enumerate(self.arquivos):
            active_orig_idx = self.arquivos_originais.index(active_path)
            if active_orig_idx > orig_idx:
                insert_idx = i
                break
        else:
            insert_idx = len(self.arquivos)
            
        self.arquivos.insert(insert_idx, recovered_path)
        self.current_index = insert_idx
        
        self.btn_desfazer.configure(state="normal" if self.descartados else "disabled")
        self.exibir_foto_atual()

    def finalizar_revisao(self):
        total_descartados = len(self.descartados)
        if total_descartados > 0:
            confirmar = messagebox.askyesno(
                "Confirmar Exclusão", 
                f"Você marcou {total_descartados} foto(s) para exclusão.\n\n"
                "Elas serão apagadas permanentemente do computador.\n"
                "Deseja continuar?"
            )
            if not confirmar:
                return
                
            # Oculta a janela de seleção imediatamente para melhor UX e libera o foco
            self.withdraw()
            self.grab_release()
            
            sucessos = 0
            erros = 0
            for path in self.descartados:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                        sucessos += 1
                except Exception as e:
                    print(f"Erro ao deletar {path}: {e}")
                    erros += 1
            
            self.parent.arquivos_transferidos = self.arquivos.copy()
            self.parent.registrar_historico(total_selecionadas=len(self.arquivos))
            
            mensagem = f"Limpeza concluída! {sucessos} foto(s) foram apagadas."
            if erros > 0:
                mensagem += f"\n(Erro ao apagar {erros} foto(s).)"
            messagebox.showinfo("Sucesso", mensagem)
        else:
            # Oculta a janela de seleção imediatamente para melhor UX e libera o foco
            self.withdraw()
            self.grab_release()
            messagebox.showinfo("Concluído", "Revisão terminada! Nenhuma foto foi apagada.")
            self.parent.registrar_historico(total_selecionadas=len(self.arquivos))
            
        self.limpar_eventos_globais()
        self.destroy()
        
        # Garante que os botões na janela principal sejam reativados corretamente
        self.parent.btn_selecionar.configure(state="normal")
        self.parent.btn_abrir.configure(state="normal")
        if self.parent.arquivos_transferidos:
            self.parent.btn_enviar_drive.configure(state="normal")
        else:
            self.parent.btn_enviar_drive.configure(state="disabled")

        # Abre a pasta contendo as fotos finais selecionadas
        self.parent.abrir_pasta()

    def ao_fechar_janela(self):
        resposta = messagebox.askyesnocancel(
            "Finalizar Seleção", 
            "Deseja salvar suas escolhas e finalizar a revisão?\n\n"
            "- 'Sim': Aplica as exclusões permanentemente e abre a pasta.\n"
            "- 'Não': Fecha sem salvar (mantém todas as fotos no computador).\n"
            "- 'Cancelar': Continua na tela de revisão de fotos."
        )
        if resposta is True:
            self.finalizar_revisao()
        elif resposta is False:
            self.limpar_eventos_globais()
            self.parent.btn_selecionar.configure(state="normal")
            self.parent.btn_abrir.configure(state="normal")
            if self.parent.arquivos_transferidos:
                self.parent.btn_enviar_drive.configure(state="normal")
            self.grab_release()
            self.destroy()


class HistoricoDadosWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Histórico e Dados de Descarregamento")
        self.geometry("800x550")
        self.minsize(800, 550)
        
        # Foco e grab_set seguro
        self.focus_force()
        self.after(100, lambda: self.grab_set() if self.winfo_exists() else None)
        
        self.caminho_hist = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historico_downloads.json")
        self.setup_ui()
        self.carregar_e_exibir()

    def setup_ui(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        # Header
        self.frame_header = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_header.grid(row=0, column=0, padx=20, pady=(15, 5), sticky="ew")
        
        self.frame_header.grid_columnconfigure(0, weight=1)
        self.frame_header.grid_columnconfigure(1, weight=0)
        
        self.lbl_titulo = ctk.CTkLabel(
            self.frame_header, 
            text="Histórico Recente de Transferências", 
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.lbl_titulo.grid(row=0, column=0, sticky="w")
        
        self.btn_limpar = ctk.CTkButton(
            self.frame_header, 
            text="🗑️ Limpar Histórico", 
            width=120,
            height=28,
            fg_color="#e74c3c",
            hover_color="#c0392b",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.limpar_historico
        )
        self.btn_limpar.grid(row=0, column=1, sticky="e")
        
        # Scrollable Frame para o histórico
        self.scroll_lista = ctk.CTkScrollableFrame(self, fg_color="#1a1a1a")
        self.scroll_lista.grid(row=1, column=0, padx=20, pady=5, sticky="nsew")
        
        # Botão Fechar no rodapé
        self.btn_fechar = ctk.CTkButton(
            self, 
            text="Fechar", 
            height=32,
            font=ctk.CTkFont(weight="bold"),
            command=self.fechar_janela
        )
        self.btn_fechar.grid(row=2, column=0, padx=20, pady=15, sticky="ew")

    def carregar_e_exibir(self):
        for widget in self.scroll_lista.winfo_children():
            widget.destroy()
            
        historico = []
        if os.path.exists(self.caminho_hist):
            try:
                with open(self.caminho_hist, 'r', encoding='utf-8') as f:
                    historico = json.load(f)
            except Exception:
                pass
                
        if not historico:
            lbl_vazio = ctk.CTkLabel(
                self.scroll_lista, 
                text="Nenhum registro de descarregamento encontrado.", 
                text_color="gray",
                font=ctk.CTkFont(size=13)
            )
            lbl_vazio.pack(pady=40)
            return
            
        for item in reversed(historico):
            frame_item = ctk.CTkFrame(self.scroll_lista, fg_color="#2b2b2b")
            frame_item.pack(fill="x", pady=6, padx=5)
            
            data_formatada = item.get("data", "")
            try:
                partes = data_formatada.split("-")
                if len(partes) == 3:
                    data_formatada = f"{partes[2]}/{partes[1]}/{partes[0]}"
            except Exception:
                pass
                
            texto_info = (
                f"📅 {data_formatada} às {item.get('hora', '')}\n"
                f"👤 Fotógrafo: {item.get('fotografo', '')}\n"
                f"📥 Copiadas: {item.get('descarregadas', 0)}  |  ✅ Selecionadas: {item.get('selecionadas', 0)}\n"
                f"📁 Caminho: {item.get('destino', '')}"
            )
            
            lbl_info = ctk.CTkLabel(
                frame_item, 
                text=texto_info, 
                font=ctk.CTkFont(size=12),
                justify="left",
                anchor="w"
            )
            lbl_info.pack(side="left", padx=15, pady=10, fill="x", expand=True)
            
            btn_abrir_pasta = ctk.CTkButton(
                frame_item, 
                text="📁 Abrir Pasta", 
                width=100, 
                height=28,
                fg_color="#1f538d", 
                hover_color="#14375e",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda p=item.get('destino', ''): self.abrir_pasta_historico(p)
            )
            btn_abrir_pasta.pack(side="right", padx=15, pady=10)

    def abrir_pasta_historico(self, pasta):
        if not pasta:
            return
        if os.path.exists(pasta):
            if platform.system() == "Windows":
                os.startfile(pasta)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", pasta])
            else:
                subprocess.Popen(["xdg-open", pasta])
        else:
            messagebox.showwarning("Pasta Não Encontrada", f"A pasta '{pasta}' não existe ou foi movida/deletada.")

    def limpar_historico(self):
        confirmar = messagebox.askyesno("Limpar Histórico", "Deseja realmente limpar todo o histórico de dados?")
        if confirmar:
            try:
                if os.path.exists(self.caminho_hist):
                    os.remove(self.caminho_hist)
                self.carregar_e_exibir()
            except Exception as e:
                messagebox.showerror("Erro", f"Não foi possível limpar o histórico: {e}")

    def fechar_janela(self):
        self.grab_release()
        self.destroy()


class ConfiguradorDriveWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Configurações do Líder - Pastas")
        self.geometry("750x650")
        self.minsize(750, 650)
        
        # Foco e grab_set seguro
        self.focus_force()
        self.after(100, lambda: self.grab_set() if self.winfo_exists() else None)
        
        self.caminho_config = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_pastas.json")
        self.pastas = []
        self.pastas_local = []
        self.carregar_config()
        
        self.setup_ui()
        self.atualizar_lista()
        self.atualizar_lista_local()

    def carregar_config(self):
        if os.path.exists(self.caminho_config):
            try:
                with open(self.caminho_config, 'r', encoding='utf-8') as f:
                    dados = json.load(f)
                    if isinstance(dados, dict) and "data" in dados:
                        hoje = date.today().isoformat()
                        if dados["data"] == hoje:
                            self.pastas = dados.get("pastas", [])
                            self.pastas_local = dados.get("pastas_local", [])
                            return
            except Exception as e:
                print(f"Erro ao carregar JSON: {e}")
        self.pastas = []
        self.pastas_local = []

    def salvar_config(self):
        try:
            hoje = date.today().isoformat()
            dados = {
                "data": hoje,
                "pastas": self.pastas,
                "pastas_local": self.pastas_local
            }
            with open(self.caminho_config, 'w', encoding='utf-8') as f:
                json.dump(dados, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível salvar as configurações: {e}")
            return False

    def setup_ui(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        # Título
        self.lbl_titulo = ctk.CTkLabel(
            self, 
            text="Configurações do Líder - Pastas Pré-definidas", 
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.lbl_titulo.grid(row=0, column=0, pady=(15, 5), padx=20, sticky="w")
        
        # Tabview para separar Google Drive e Computador
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=1, column=0, padx=20, pady=5, sticky="nsew")
        
        self.tabview.add("Google Drive")
        self.tabview.add("Computador")
        
        # --- TAB GOOGLE DRIVE ---
        tab_drive = self.tabview.tab("Google Drive")
        tab_drive.grid_rowconfigure(0, weight=1)
        tab_drive.grid_columnconfigure(0, weight=1)
        
        # Lista de Pastas (Scrollable Frame)
        self.scroll_lista = ctk.CTkScrollableFrame(tab_drive, fg_color="#1a1a1a")
        self.scroll_lista.grid(row=0, column=0, padx=10, pady=5, sticky="nsew")
        
        # Container de adição de nova pasta
        self.frame_adicionar = ctk.CTkFrame(tab_drive, fg_color="#242424")
        self.frame_adicionar.grid(row=1, column=0, padx=10, pady=(10, 10), sticky="ew")
        
        self.frame_adicionar.grid_columnconfigure(0, weight=1)
        self.frame_adicionar.grid_columnconfigure(1, weight=0)
        
        # Campos de entrada
        self.lbl_add_titulo = ctk.CTkLabel(
            self.frame_adicionar, 
            text="Adicionar Nova Pasta do Google Drive", 
            font=ctk.CTkFont(weight="bold")
        )
        self.lbl_add_titulo.grid(row=0, column=0, columnspan=2, padx=15, pady=(10, 5), sticky="w")
        
        # Link do Drive
        self.entry_link = ctk.CTkEntry(
            self.frame_adicionar, 
            placeholder_text="Cole o link ou ID da pasta do Google Drive aqui..."
        )
        self.entry_link.grid(row=1, column=0, columnspan=2, padx=15, pady=5, sticky="ew")
        
        # Nome personalizado (opcional)
        self.entry_nome_pasta = ctk.CTkEntry(
            self.frame_adicionar, 
            placeholder_text="Nome da Pasta (Deixe vazio para buscar automaticamente do Drive)"
        )
        self.entry_nome_pasta.grid(row=2, column=0, padx=15, pady=5, sticky="ew")
        
        # Botões de ação de adição
        self.btn_add = ctk.CTkButton(
            self.frame_adicionar, 
            text="Adicionar", 
            fg_color="#2ecc71", 
            hover_color="#27ae60",
            font=ctk.CTkFont(weight="bold"),
            command=self.adicionar_pasta
        )
        self.btn_add.grid(row=2, column=1, padx=15, pady=5, sticky="ew")
        
        # --- TAB COMPUTADOR ---
        tab_local = self.tabview.tab("Computador")
        tab_local.grid_rowconfigure(0, weight=1)
        tab_local.grid_columnconfigure(0, weight=1)
        
        # Lista de Pastas do Computador (Scrollable Frame)
        self.scroll_lista_local = ctk.CTkScrollableFrame(tab_local, fg_color="#1a1a1a")
        self.scroll_lista_local.grid(row=0, column=0, padx=10, pady=5, sticky="nsew")
        
        # Container de adição de nova pasta do Computador
        self.frame_adicionar_local = ctk.CTkFrame(tab_local, fg_color="#242424")
        self.frame_adicionar_local.grid(row=1, column=0, padx=10, pady=(10, 10), sticky="ew")
        
        self.frame_adicionar_local.grid_columnconfigure(0, weight=1)
        self.frame_adicionar_local.grid_columnconfigure(1, weight=0)
        
        self.lbl_add_titulo_local = ctk.CTkLabel(
            self.frame_adicionar_local, 
            text="Adicionar Nova Pasta do Computador", 
            font=ctk.CTkFont(weight="bold")
        )
        self.lbl_add_titulo_local.grid(row=0, column=0, columnspan=2, padx=15, pady=(10, 5), sticky="w")
        
        # Sub-frame para o caminho da pasta
        self.frame_caminho_local = ctk.CTkFrame(self.frame_adicionar_local, fg_color="transparent")
        self.frame_caminho_local.grid(row=1, column=0, columnspan=2, padx=15, pady=5, sticky="ew")
        self.frame_caminho_local.grid_columnconfigure(0, weight=1)
        
        self.entry_caminho_local = ctk.CTkEntry(
            self.frame_caminho_local, 
            placeholder_text="Caminho da pasta no computador..."
        )
        self.entry_caminho_local.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        
        self.btn_procurar_local = ctk.CTkButton(
            self.frame_caminho_local, 
            text="Procurar...", 
            width=100,
            command=self.procurar_caminho_local
        )
        self.btn_procurar_local.grid(row=0, column=1, sticky="ew")
        
        # Nome personalizado
        self.entry_nome_local = ctk.CTkEntry(
            self.frame_adicionar_local, 
            placeholder_text="Nome de Exibição (Opcional - preenchido automaticamente)"
        )
        self.entry_nome_local.grid(row=2, column=0, padx=15, pady=5, sticky="ew")
        
        self.btn_add_local = ctk.CTkButton(
            self.frame_adicionar_local, 
            text="Adicionar", 
            fg_color="#2ecc71", 
            hover_color="#27ae60",
            font=ctk.CTkFont(weight="bold"),
            command=self.adicionar_pasta_local
        )
        self.btn_add_local.grid(row=2, column=1, padx=15, pady=5, sticky="ew")

        # Botão Salvar e Fechar no rodapé
        self.btn_salvar_fechar = ctk.CTkButton(
            self, 
            text="Salvar e Fechar", 
            height=32,
            font=ctk.CTkFont(weight="bold"),
            command=self.salvar_e_fechar
        )
        self.btn_salvar_fechar.grid(row=2, column=0, padx=20, pady=(0, 15), sticky="ew")

    def obter_nome_pasta_drive(self, link_ou_id):
        if not GOOGLE_DRIVE_DISPONIVEL:
            return None
        folder_id = self.parent.extrair_id_pasta_drive(link_ou_id)
        if folder_id == 'root':
            return "Raiz do Google Drive"
            
        caminho_credenciais = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")
        if not os.path.exists(caminho_credenciais):
            return None
            
        SCOPES = ['https://www.googleapis.com/auth/drive']
        token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'token.json')
        creds = None
        if os.path.exists(token_path):
            try:
                creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            except Exception:
                pass
        
        if not creds or not creds.valid:
            return None
            
        try:
            service = build('drive', 'v3', credentials=creds)
            pasta_meta = service.files().get(fileId=folder_id, fields='name').execute()
            return pasta_meta.get('name')
        except Exception as e:
            print(f"Erro ao obter nome da pasta no Drive: {e}")
            return None

    def adicionar_pasta(self):
        link = self.entry_link.get().strip()
        if not link:
            messagebox.showwarning("Aviso", "Insira o link ou ID da pasta do Google Drive!")
            return
            
        nome = self.entry_nome_pasta.get().strip()
        
        if not nome:
            nome_detectado = self.obter_nome_pasta_drive(link)
            if nome_detectado:
                nome = nome_detectado
            else:
                id_pasta = self.parent.extrair_id_pasta_drive(link)
                nome = f"Pasta ({id_pasta[:8]}...)"
                
        self.pastas.append({
            "nome": nome,
            "link": link
        })
        
        self.entry_link.delete(0, 'end')
        self.entry_nome_pasta.delete(0, 'end')
        
        self.atualizar_lista()

    def remover_pasta(self, index):
        if 0 <= index < len(self.pastas):
            del self.pastas[index]
            self.atualizar_lista()

    def atualizar_lista(self):
        for widget in self.scroll_lista.winfo_children():
            widget.destroy()
            
        if not self.pastas:
            lbl_vazio = ctk.CTkLabel(
                self.scroll_lista, 
                text="Nenhuma pasta configurada. Adicione uma pasta abaixo.", 
                text_color="gray"
            )
            lbl_vazio.pack(pady=30)
            return
            
        for i, item in enumerate(self.pastas):
            frame_item = ctk.CTkFrame(self.scroll_lista, fg_color="#2b2b2b", cursor="hand2")
            frame_item.pack(fill="x", pady=4, padx=5)
            
            lbl_info = ctk.CTkLabel(
                frame_item, 
                text=f"📁 {item['nome']}\nLink/ID: {item['link']}", 
                font=ctk.CTkFont(size=12),
                justify="left",
                anchor="w",
                cursor="hand2"
            )
            lbl_info.pack(side="left", padx=10, pady=6, fill="x", expand=True)
            
            # Clique para abrir a pasta no Google Drive
            frame_item.bind("<Button-1>", lambda event, link=item['link']: self.abrir_link_drive(link))
            lbl_info.bind("<Button-1>", lambda event, link=item['link']: self.abrir_link_drive(link))
            
            btn_remove = ctk.CTkButton(
                frame_item, 
                text="Remover", 
                width=60, 
                height=24,
                fg_color="#e74c3c", 
                hover_color="#c0392b",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda idx=i: self.remover_pasta(idx)
            )
            btn_remove.pack(side="right", padx=(5, 10), pady=6)

            btn_abrir = ctk.CTkButton(
                frame_item, 
                text="Abrir no Drive", 
                width=90, 
                height=24,
                fg_color="#1f538d", 
                hover_color="#14375e",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda link=item['link']: self.abrir_link_drive(link)
            )
            btn_abrir.pack(side="right", padx=(10, 5), pady=6)

    def procurar_caminho_local(self):
        pasta = filedialog.askdirectory(title="Selecione a pasta do computador")
        if pasta:
            self.entry_caminho_local.delete(0, 'end')
            self.entry_caminho_local.insert(0, pasta)
            # Preenche automaticamente o nome com o nome da pasta selecionada
            nome_pasta = os.path.basename(pasta.rstrip("/\\"))
            if not nome_pasta:
                nome_pasta = pasta
            self.entry_nome_local.delete(0, 'end')
            self.entry_nome_local.insert(0, nome_pasta)

    def adicionar_pasta_local(self):
        caminho = self.entry_caminho_local.get().strip()
        if not caminho:
            messagebox.showwarning("Aviso", "Selecione ou digite o caminho da pasta no computador!")
            return
            
        nome = self.entry_nome_local.get().strip()
        if not nome:
            nome = os.path.basename(caminho)
            if not nome:
                nome = caminho
                
        self.pastas_local.append({
            "nome": nome,
            "caminho": caminho
        })
        
        self.entry_caminho_local.delete(0, 'end')
        self.entry_nome_local.delete(0, 'end')
        
        self.atualizar_lista_local()

    def remover_pasta_local(self, index):
        if 0 <= index < len(self.pastas_local):
            del self.pastas_local[index]
            self.atualizar_lista_local()

    def atualizar_lista_local(self):
        for widget in self.scroll_lista_local.winfo_children():
            widget.destroy()
            
        if not self.pastas_local:
            lbl_vazio = ctk.CTkLabel(
                self.scroll_lista_local, 
                text="Nenhuma pasta local configurada. Adicione uma pasta abaixo.", 
                text_color="gray"
            )
            lbl_vazio.pack(pady=30)
            return
            
        for i, item in enumerate(self.pastas_local):
            frame_item = ctk.CTkFrame(self.scroll_lista_local, fg_color="#2b2b2b", cursor="hand2")
            frame_item.pack(fill="x", pady=4, padx=5)
            
            lbl_info = ctk.CTkLabel(
                frame_item, 
                text=f"📁 {item['nome']}\nCaminho: {item['caminho']}", 
                font=ctk.CTkFont(size=12),
                justify="left",
                anchor="w",
                cursor="hand2"
            )
            lbl_info.pack(side="left", padx=10, pady=6, fill="x", expand=True)
            
            # Clique para abrir a pasta local
            frame_item.bind("<Button-1>", lambda event, caminho=item['caminho']: self.abrir_pasta_local(caminho))
            lbl_info.bind("<Button-1>", lambda event, caminho=item['caminho']: self.abrir_pasta_local(caminho))
            
            btn_remove = ctk.CTkButton(
                frame_item, 
                text="Remover", 
                width=60, 
                height=24,
                fg_color="#e74c3c", 
                hover_color="#c0392b",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda idx=i: self.remover_pasta_local(idx)
            )
            btn_remove.pack(side="right", padx=(5, 10), pady=6)

            btn_abrir = ctk.CTkButton(
                frame_item, 
                text="Abrir Pasta", 
                width=80, 
                height=24,
                fg_color="#1f538d", 
                hover_color="#14375e",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda caminho=item['caminho']: self.abrir_pasta_local(caminho)
            )
            btn_abrir.pack(side="right", padx=(10, 5), pady=6)

    def salvar_e_fechar(self):
        if self.salvar_config():
            self.parent.recarregar_combo_drive()
            self.parent.recarregar_combo_destino()
            self.grab_release()
            self.destroy()

    def abrir_link_drive(self, link_ou_id):
        if not link_ou_id:
            return
        id_pasta = self.parent.extrair_id_pasta_drive(link_ou_id)
        if id_pasta == 'root':
            url = "https://drive.google.com/drive/my-drive"
        else:
            url = f"https://drive.google.com/drive/folders/{id_pasta}"
        
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível abrir o link no navegador: {e}")

    def abrir_pasta_local(self, pasta):
        if not pasta:
            return
        if os.path.exists(pasta):
            try:
                if platform.system() == "Windows":
                    os.startfile(pasta)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", pasta])
                else:
                    subprocess.Popen(["xdg-open", pasta])
            except Exception as e:
                messagebox.showerror("Erro", f"Não foi possível abrir a pasta: {e}")
        else:
            messagebox.showwarning("Pasta Não Encontrada", f"A pasta '{pasta}' não existe ou foi movida/deletada.")


def sincronizar_credenciais_env():
    # Caminho do .env e credentials.json
    dir_atual = os.path.dirname(os.path.abspath(__file__))
    caminho_env = os.path.join(dir_atual, ".env")
    caminho_credenciais = os.path.join(dir_atual, "credentials.json")
    token_path = os.path.join(dir_atual, "token.json")
    
    if not os.path.exists(caminho_env):
        return
        
    client_id = None
    client_secret = None
    
    try:
        with open(caminho_env, 'r', encoding='utf-8') as f:
            linhas = f.read().splitlines()
            
        # 1. Tenta encontrar por padrões conhecidos do Google OAuth
        for linha in linhas:
            linha_limpa = linha.strip()
            if not linha_limpa:
                continue
            if ".apps.googleusercontent.com" in linha_limpa:
                if "=" in linha_limpa:
                    client_id = linha_limpa.split("=", 1)[1].strip().strip('"\'')
                else:
                    client_id = linha_limpa
            elif "GOCSPX-" in linha_limpa:
                if "=" in linha_limpa:
                    client_secret = linha_limpa.split("=", 1)[1].strip().strip('"\'')
                else:
                    client_secret = linha_limpa
                    
        # 2. Fallback por ordem de linhas não vazias se não detectou por padrão
        linhas_validas = [l.strip() for l in linhas if l.strip()]
        if not client_id and len(linhas_validas) >= 1:
            client_id = linhas_validas[0]
        if not client_secret and len(linhas_validas) >= 2:
            if len(linhas_validas) == 2:
                client_secret = linhas_validas[1]
            elif len(linhas_validas) > 2:
                client_secret = linhas_validas[2]
                
        # Limpa aspas ou espaços remanescentes
        if client_id:
            client_id = client_id.strip().strip('"\'')
        if client_secret:
            client_secret = client_secret.strip().strip('"\'')
            
        if not client_id or not client_secret:
            print("Não foi possível identificar Client ID e Client Secret no arquivo .env")
            return
            
        # Carrega credentials.json existente se houver para comparar
        dados_cred = {}
        if os.path.exists(caminho_credenciais):
            try:
                with open(caminho_credenciais, 'r', encoding='utf-8') as f:
                    dados_cred = json.load(f)
            except Exception:
                pass
                
        installed_data = dados_cred.get("installed", {})
        id_atual = installed_data.get("client_id")
        secret_atual = installed_data.get("client_secret")
        
        # Se os dados mudaram ou o arquivo não existia, cria/sobrescreve
        if id_atual != client_id or secret_atual != client_secret:
            novos_dados = {
                "installed": {
                    "client_id": client_id,
                    "project_id": installed_data.get("project_id", "descarregar-foto"),
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "client_secret": client_secret,
                    "redirect_uris": ["http://localhost"]
                }
            }
            
            with open(caminho_credenciais, 'w', encoding='utf-8') as f:
                json.dump(novos_dados, f, indent=4)
            print("Arquivo credentials.json gerado/atualizado com sucesso a partir do .env!")
            
            # Se mudou a credencial, removemos o token.json para forçar login correto
            if os.path.exists(token_path):
                try:
                    os.remove(token_path)
                    print("token.json antigo removido para evitar conflito com as novas credenciais.")
                except Exception as e:
                    print(f"Erro ao remover token.json antigo: {e}")
                    
    except Exception as e:
        print(f"Erro ao sincronizar credenciais do .env: {e}")


def obter_ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def mesclar_estatisticas(stats_lider, stats_auxiliares):
    mapa_categorias = {}
    
    def adicionar_stats(lista_cat):
        for cat in lista_cat:
            cat_nome = cat.get("nome")
            if not cat_nome:
                continue
            if cat_nome not in mapa_categorias:
                mapa_categorias[cat_nome] = {}
            
            for fotog in cat.get("fotografos", []):
                f_nome = fotog.get("nome_fotografo")
                f_total = fotog.get("total_fotos", 0)
                f_cameras = fotog.get("cameras", [])
                f_lentes = fotog.get("lentes", [])
                if f_nome:
                    if f_nome not in mapa_categorias[cat_nome]:
                        mapa_categorias[cat_nome][f_nome] = {
                            "total_fotos": 0,
                            "cameras": set(),
                            "lentes": set()
                        }
                    mapa_categorias[cat_nome][f_nome]["total_fotos"] += f_total
                    mapa_categorias[cat_nome][f_nome]["cameras"].update(f_cameras)
                    mapa_categorias[cat_nome][f_nome]["lentes"].update(f_lentes)
                    
    adicionar_stats(stats_lider)
    for sa in stats_auxiliares:
        adicionar_stats(sa)
        
    resultado = []
    for cat_nome, fotogs_map in mapa_categorias.items():
        fotogs_list = []
        for name, data in fotogs_map.items():
            fotogs_list.append({
                "nome_fotografo": name,
                "total_fotos": data["total_fotos"],
                "cameras": list(data["cameras"]),
                "lentes": list(data["lentes"])
            })
        resultado.append({
            "nome": cat_nome,
            "fotografos": fotogs_list
        })
    return resultado

class AppRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        app = self.server.app_instance
        parsed_url = urllib.parse.urlparse(self.path)
        
        if parsed_url.path == "/preset":
            if app.active_servir:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(app.active_servir).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"No active servir event")
                
        elif parsed_url.path == "/stats":
            stats = app.obter_estatisticas_locais()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"categorias": stats}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        app = self.server.app_instance
        parsed_url = urllib.parse.urlparse(self.path)
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""
        
        if parsed_url.path == "/register":
            try:
                dados = json.loads(body.decode("utf-8"))
                ip = dados.get("ip")
                nome = dados.get("nome")
                porta = dados.get("port", 50007)
                if ip and nome:
                    app.auxiliar_stations[ip] = {
                        "nome": nome,
                        "port": porta,
                        "last_seen": time.time()
                    }
                    app.after(0, app.atualizar_lista_auxiliares_ui)
                    
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
                else:
                    self.send_response(400)
                    self.end_headers()
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode("utf-8"))
                
        elif parsed_url.path == "/finalize":
            app.after(0, app.finalizar_servir_remotamente)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

def iniciar_servidor_lan(app, porta_inicial=50007):
    porta = porta_inicial
    server = None
    while porta < porta_inicial + 10:
        try:
            server = HTTPServer(('', porta), AppRequestHandler)
            server.app_instance = app
            app.local_port = porta
            break
        except Exception:
            porta += 1
            
    if not server:
        print("Erro: Não foi possível iniciar o servidor LAN.")
        return
        
    app.lan_server = server
    print(f"Servidor LAN rodando na porta {porta}")
    try:
        server.serve_forever()
    except Exception:
        pass

def parar_servidor_lan(app):
    if hasattr(app, 'lan_server') and app.lan_server:
        try:
            app.lan_server.shutdown()
            app.lan_server.server_close()
        except Exception as e:
            print(f"Erro ao fechar servidor: {e}")
        app.lan_server = None

def transmitir_broadcast_lider(app):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(1.0)
    
    while True:
        if not hasattr(app, 'network_mode') or app.network_mode != "lider":
            break
        if not app.active_servir:
            time.sleep(2.0)
            continue
            
        try:
            ip_local = obter_ip_local()
            nome_evento = app.active_servir.get("nome", "Servir")
            evento_id = app.active_servir.get("id", "0")
            msg = f"SERVIR_LEADER:{ip_local}:{app.local_port}:{nome_evento}:{evento_id}"
            sock.sendto(msg.encode("utf-8"), ('<broadcast>', 50008))
        except Exception as e:
            print(f"Erro no broadcast UDP: {e}")
            
        time.sleep(3.0)
    sock.close()

def escutar_broadcast_auxiliar(app):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        pass
    
    try:
        sock.bind(('', 50008))
    except Exception as e:
        print(f"Erro ao bindar porta UDP: {e}")
        sock.close()
        return
        
    sock.settimeout(1.0)
    
    while True:
        if not hasattr(app, 'network_mode') or app.network_mode != "auxiliar":
            break
        if app.active_servir:
            time.sleep(2.0)
            continue
            
        try:
            data, addr = sock.recvfrom(1024)
            msg = data.decode("utf-8")
            if msg.startswith("SERVIR_LEADER:"):
                partes = msg.split(":")
                if len(partes) >= 5:
                    ip_lider = partes[1]
                    port_lider = int(partes[2])
                    nome_evento = partes[3]
                    evento_id = partes[4]
                    
                    app.lider_detectado = {
                        "ip": ip_lider,
                        "port": port_lider,
                        "nome_evento": nome_evento,
                        "evento_id": evento_id
                    }
                    app.after(0, app.atualizar_lider_detectado_ui)
        except socket.timeout:
            continue
        except Exception as e:
            print(f"Erro ao receber broadcast: {e}")
            
    sock.close()


class ImportadorFotosApp(ctk.CTk):
    def __init__(self):
        sincronizar_credenciais_env()
        super().__init__()

        self.title("Descarregador de Fotos - Ministério")
        self.geometry("1020x800")
        self.resizable(True, True)
        self.minsize(1000, 800)

        self.destino_path = ctk.StringVar()
        self.cartao_detectado = False
        self.origem_manual = False      # Flag para indicar seleção manual de pasta
        self.drive_path = ""
        self.checkboxes_pastas = []
        self.arquivos_transferidos = [] # Guarda o caminho de todas as fotos transferidas com sucesso
        self.active_servir = None       # Dia de servir ativo atualmente
        self.servir_em_edicao = None    # Dia de servir sendo editado atualmente
        self.lista_drive_temp = []
        self.local_path_temp = ctk.StringVar(value="")
        
        # Configurações de Rede Local (LAN)
        self.network_mode = "lider"      # "lider" ou "auxiliar"
        self.local_port = 50007
        self.auxiliar_stations = {}      # ip -> {"nome": nome, "port": port, "last_seen": timestamp}
        self.lider_detectado = None      # {"ip": ip, "port": port, "nome_evento": nome, "evento_id": id}
        
        self.lan_server_thread = None
        self.lan_broadcast_thread = None
        
        self.protocol("WM_DELETE_WINDOW", self.fechar_aplicativo)

        # Pasta padrão dentro do diretório do app
        self.destino_padrao_app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Fotos_Sistema")
        os.makedirs(self.destino_padrao_app, exist_ok=True)

        # Carrega configuração de pastas do Drive e locais para o líder
        self.caminho_config_pastas = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_pastas.json")
        self.caminho_dias_servir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dias_servir.json")
        self.pastas_drive = self.carregar_config_pastas()
        self.pastas_local = self.carregar_config_pastas_local()
        
        self.iniciar_servicos_rede()
        self.mostrar_pagina_inicial()
        
        self.monitor_thread = threading.Thread(target=self.monitorar_cartao, daemon=True)
        self.monitor_thread.start()

    def carregar_config_pastas(self):
        if os.path.exists(self.caminho_config_pastas):
            try:
                with open(self.caminho_config_pastas, 'r', encoding='utf-8') as f:
                    dados = json.load(f)
                    if isinstance(dados, dict) and "data" in dados and "pastas" in dados:
                        hoje = date.today().isoformat()
                        if dados["data"] == hoje:
                            return dados["pastas"]
            except Exception as e:
                print(f"Erro ao carregar pastas do Drive: {e}")
        return []

    def carregar_config_pastas_local(self):
        if os.path.exists(self.caminho_config_pastas):
            try:
                with open(self.caminho_config_pastas, 'r', encoding='utf-8') as f:
                    dados = json.load(f)
                    if isinstance(dados, dict) and "data" in dados:
                        hoje = date.today().isoformat()
                        if dados["data"] == hoje:
                            return dados.get("pastas_local", [])
            except Exception as e:
                print(f"Erro ao carregar pastas locais: {e}")
        return []

    def carregar_dias_servir(self):
        if os.path.exists(self.caminho_dias_servir):
            try:
                with open(self.caminho_dias_servir, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Erro ao carregar dias de servir: {e}")
        return []

    def salvar_dias_servir(self, dias):
        try:
            with open(self.caminho_dias_servir, 'w', encoding='utf-8') as f:
                json.dump(dias, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Erro ao salvar dias de servir: {e}")
            return False

    def iniciar_servicos_rede(self):
        self.parar_servicos_rede()
        
        # Ambos rodam um servidor HTTP local
        self.lan_server_thread = threading.Thread(target=iniciar_servidor_lan, args=(self,), daemon=True)
        self.lan_server_thread.start()
        
        if self.network_mode == "lider":
            self.lan_broadcast_thread = threading.Thread(target=transmitir_broadcast_lider, args=(self,), daemon=True)
            self.lan_broadcast_thread.start()
        else:
            self.lider_detectado = None
            self.lan_broadcast_thread = threading.Thread(target=escutar_broadcast_auxiliar, args=(self,), daemon=True)
            self.lan_broadcast_thread.start()

    def parar_servicos_rede(self):
        parar_servidor_lan(self)
        self.auxiliar_stations.clear()
        self.lider_detectado = None

    def fechar_aplicativo(self):
        self.parar_servicos_rede()
        self.destroy()

    def finalizar_servir_remotamente(self):
        self.active_servir = None
        self.arquivos_transferidos.clear()
        messagebox.showinfo("Servir Finalizado", "O computador Líder finalizou o Dia de Servir.\nSua estação foi desconectada automaticamente.")
        self.mostrar_pagina_inicial()

    def extrair_camera_e_lente(self, caminho_arquivo):
        camera = "Desconhecida"
        lente = "Desconhecida"
        
        ext = caminho_arquivo.lower()
        if ext.endswith(('.mp4', '.mov', '.avi', '.wav')):
            return camera, lente
            
        try:
            with Image.open(caminho_arquivo) as img:
                exif = img.getexif()
                if exif:
                    make = exif.get(271)
                    model = exif.get(272)
                    
                    if model:
                        model = str(model).strip()
                        if make and str(make).strip() not in model:
                            camera = f"{str(make).strip()} {model}"
                        else:
                            camera = model
                    elif make:
                        camera = str(make).strip()
                    
                    try:
                        exif_ifd = exif.get_ifd(34665)
                        if exif_ifd:
                            lens_make = exif_ifd.get(42035)
                            lens_model = exif_ifd.get(42036)
                            if lens_model:
                                lens_model = str(lens_model).strip()
                                if lens_make and str(lens_make).strip() not in lens_model:
                                    lente = f"{str(lens_make).strip()} {lens_model}"
                                else:
                                    lente = lens_model
                            elif lens_make:
                                lente = str(lens_make).strip()
                    except Exception:
                        pass
                        
                    if lente == "Desconhecida":
                        from PIL.ExifTags import TAGS
                        for tag_id, val in exif.items():
                            tag_name = TAGS.get(tag_id, tag_id)
                            if tag_name in ('LensModel', 'LensName'):
                                lente = str(val).strip()
                                break
        except Exception:
            pass
            
        return camera, lente

    def obter_estatisticas_locais(self):
        if not self.active_servir:
            return []
        nome_servir = self.active_servir.get('nome')
        destino_base = self.destino_path.get()
        pasta_raiz_servir = os.path.join(destino_base, nome_servir)
        
        categorias_detectadas = {}
        if os.path.exists(pasta_raiz_servir):
            for item in os.listdir(pasta_raiz_servir):
                caminho_item = os.path.join(pasta_raiz_servir, item)
                if os.path.isdir(caminho_item):
                    categoria_nome = item
                    categorias_detectadas[categoria_nome] = []
                    
                    for subitem in os.listdir(caminho_item):
                        caminho_subitem = os.path.join(caminho_item, subitem)
                        if os.path.isdir(caminho_subitem):
                            fotografo_dir_nome = subitem
                            
                            total_fotos = 0
                            cameras_usadas = set()
                            lentes_usadas = set()
                            
                            for root, _, files in os.walk(caminho_subitem):
                                for file_name in files:
                                    if file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.cr2', '.nef', '.arw', '.cr3', '.mp4')):
                                        total_fotos += 1
                                        if file_name.lower().endswith(('.jpg', '.jpeg', '.png', '.cr2', '.nef', '.arw', '.cr3')):
                                            caminho_foto = os.path.join(root, file_name)
                                            cam, len_ = self.extrair_camera_e_lente(caminho_foto)
                                            if cam and cam != "Desconhecida":
                                                cameras_usadas.add(cam)
                                            if len_ and len_ != "Desconhecida":
                                                lentes_usadas.add(len_)
                            
                            categorias_detectadas[categoria_nome].append({
                                "nome_fotografo": fotografo_dir_nome,
                                "total_fotos": total_fotos,
                                "cameras": list(cameras_usadas),
                                "lentes": list(lentes_usadas)
                            })
        
        lista_categorias = []
        for cat_nome, fotogs in categorias_detectadas.items():
            lista_categorias.append({
                "nome": cat_nome,
                "fotografos": fotogs
            })
        return lista_categorias

    def mudar_modo_rede(self, modo_selecionado):
        if "Líder" in modo_selecionado:
            self.network_mode = "lider"
        else:
            self.network_mode = "auxiliar"
            
        self.iniciar_servicos_rede()
        self.mostrar_pagina_inicial()

    def reiniciar_rede_botao(self):
        self.iniciar_servicos_rede()
        messagebox.showinfo("Rede Local", "Serviços de rede local reiniciados com sucesso!")
        self.mostrar_pagina_inicial()

    def atualizar_lider_detectado_ui(self):
        if not hasattr(self, 'frame_sync_auxiliar') or not self.frame_sync_auxiliar.winfo_exists():
            return
            
        if self.lider_detectado:
            self.lbl_status_busca.configure(text="🟢 LÍDER ENCONTRADO!", text_color="lightgreen")
            self.lbl_lider_nome.configure(text=f"Evento: {self.lider_detectado['nome_evento']}")
            self.lbl_lider_ip.configure(text=f"Líder IP: {self.lider_detectado['ip']}:{self.lider_detectado['port']}")
            self.frame_dados_lider.pack(pady=10)
            self.btn_sincronizar.configure(state="normal")
        else:
            self.lbl_status_busca.configure(text="🔍 Procurando Líder na rede local...", text_color="orange")
            self.frame_dados_lider.pack_forget()
            self.btn_sincronizar.configure(state="disabled")

    def conectar_e_sincronizar_lider(self):
        if not self.lider_detectado:
            return
            
        ip = self.lider_detectado["ip"]
        port = self.lider_detectado["port"]
        
        import requests
        try:
            ip_local = obter_ip_local()
            nome_pc = platform.node() or "Estação Auxiliar"
            reg_url = f"http://{ip}:{port}/register"
            reg_payload = {"ip": ip_local, "nome": nome_pc, "port": self.local_port}
            
            res_reg = requests.post(reg_url, json=reg_payload, timeout=3.0)
            if res_reg.status_code != 200:
                messagebox.showerror("Erro de Sincronização", f"Não foi possível se registrar no líder: Código {res_reg.status_code}")
                return
                
            preset_url = f"http://{ip}:{port}/preset"
            res_preset = requests.get(preset_url, timeout=3.0)
            if res_preset.status_code == 200:
                preset = res_preset.json()
                self.active_servir = preset
                self.ativar_servir_dia(preset)
            else:
                messagebox.showerror("Erro de Sincronização", f"Não foi possível obter os dados do evento: Código {res_preset.status_code}")
        except Exception as e:
            messagebox.showerror("Erro de Conexão", f"Falha ao conectar ao Líder em {ip}:{port}:\n{e}")

    def atualizar_lista_auxiliares_ui(self):
        if not hasattr(self, 'scroll_auxiliares') or not self.scroll_auxiliares.winfo_exists():
            return
            
        for widget in self.scroll_auxiliares.winfo_children():
            widget.destroy()
            
        if not self.auxiliar_stations:
            lbl_vazio = ctk.CTkLabel(self.scroll_auxiliares, text="Nenhuma estação conectada", font=ctk.CTkFont(size=11), text_color="gray")
            lbl_vazio.pack(pady=10)
            return
            
        for ip, info in self.auxiliar_stations.items():
            frame_item = ctk.CTkFrame(self.scroll_auxiliares, fg_color="#1a1a1a", height=32, corner_radius=6)
            frame_item.pack(fill="x", pady=2, padx=2)
            
            lbl_info = ctk.CTkLabel(frame_item, text=f"💻 {info['nome']} ({ip})", font=ctk.CTkFont(size=11, weight="bold"))
            lbl_info.pack(side="left", padx=8, pady=4)
            
            lbl_status = ctk.CTkLabel(frame_item, text="🟢 Conectado", font=ctk.CTkFont(size=10), text_color="lightgreen")
            lbl_status.pack(side="right", padx=8, pady=4)

    def obter_ou_criar_pasta_drive(self, service, nome_pasta, pai_id):
        query = f"name = '{nome_pasta}' and '{pai_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        try:
            resultado = service.files().list(q=query, fields='files(id)').execute()
            arquivos = resultado.get('files', [])
            if arquivos:
                return arquivos[0]['id']
        except Exception as e:
            print(f"Erro ao buscar pasta {nome_pasta}: {e}")
            
        metadata = {
            'name': nome_pasta,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [pai_id]
        }
        try:
            pasta = service.files().create(body=metadata, fields='id').execute()
            return pasta.get('id')
        except Exception as e:
            print(f"Erro ao criar pasta {nome_pasta}: {e}")
            return None

    def abrir_configurador_drive(self):
        self.janela_config = ConfiguradorDriveWindow(self)

    def abrir_historico_dados(self):
        self.janela_dados = HistoricoDadosWindow(self)

    # --- PÁGINA INICIAL ---
    def mostrar_pagina_inicial(self):
        self.active_servir = None
        
        # Limpa widgets anteriores de forma limpa
        for widget in self.winfo_children():
            if widget != self.monitor_thread:
                try:
                    widget.pack_forget()
                    widget.grid_forget()
                    widget.destroy()
                except Exception:
                    pass
                    
        # Redimensiona a janela para a página inicial
        self.geometry("1020x800")
        self.minsize(1000, 800)
        
        # Cria container principal
        self.container_principal = ctk.CTkFrame(self, fg_color="transparent")
        self.container_principal.pack(fill="both", expand=True, padx=20, pady=20)
        
        self.container_principal.grid_rowconfigure(0, weight=0) # Header
        self.container_principal.grid_rowconfigure(1, weight=1) # Conteúdo principal
        self.container_principal.grid_columnconfigure(0, weight=1)
        
        # --- HEADER ---
        frame_header = ctk.CTkFrame(self.container_principal, fg_color="transparent")
        frame_header.grid(row=0, column=0, sticky="ew", pady=(0, 15))
        frame_header.grid_columnconfigure(0, weight=1)
        
        lbl_titulo = ctk.CTkLabel(
            frame_header, 
            text="📸 Descarregador de Fotos - Painel Inicial", 
            font=ctk.CTkFont(size=22, weight="bold")
        )
        lbl_titulo.grid(row=0, column=0, sticky="w")
        
        # Botões do cabeçalho
        frame_botoes = ctk.CTkFrame(frame_header, fg_color="transparent")
        frame_botoes.grid(row=0, column=1, sticky="e")
        
        btn_dados = ctk.CTkButton(
            frame_botoes, 
            text="📊 Histórico", 
            fg_color="#34495e", 
            hover_color="#2c3e50",
            command=self.abrir_historico_dados,
            width=100,
            height=30
        )
        btn_dados.pack(side="left", padx=5)
        
        btn_config = ctk.CTkButton(
            frame_botoes, 
            text="⚙️ Config Drive", 
            fg_color="#34495e", 
            hover_color="#2c3e50",
            command=self.abrir_configurador_drive,
            width=110,
            height=30
        )
        btn_config.pack(side="left", padx=5)
        
        # --- AREA CENTRAL (Split em 2 colunas) ---
        frame_corpo = ctk.CTkFrame(self.container_principal, fg_color="transparent")
        frame_corpo.grid(row=1, column=0, sticky="nsew")
        frame_corpo.grid_columnconfigure(0, weight=4, uniform="col") # Esquerda (Dias passados)
        frame_corpo.grid_columnconfigure(1, weight=5, uniform="col") # Direita (Criar novo)
        frame_corpo.grid_rowconfigure(0, weight=1)
        
        # --- COLUNA ESQUERDA: DIAS DO SERVIR SALVOS ---
        frame_esquerda = ctk.CTkFrame(frame_corpo, fg_color="#1e1e1e", corner_radius=12, border_width=1, border_color="#2b2b2b")
        frame_esquerda.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        frame_esquerda.grid_rowconfigure(1, weight=1)
        frame_esquerda.grid_rowconfigure(3, weight=0)
        frame_esquerda.grid_columnconfigure(0, weight=1)
        
        lbl_esq_titulo = ctk.CTkLabel(
            frame_esquerda, 
            text="Dias de Servir Anteriores", 
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#3498db"
        )
        lbl_esq_titulo.grid(row=0, column=0, sticky="w", padx=15, pady=12)
        
        self.scroll_dias = ctk.CTkScrollableFrame(frame_esquerda, fg_color="transparent")
        self.scroll_dias.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 5))
        
        # Botão Modo Avulso no rodapé da coluna esquerda
        btn_avulso = ctk.CTkButton(
            frame_esquerda,
            text="📂 Modo Avulso (Sem Dia de Servir)",
            fg_color="#7f8c8d",
            hover_color="#95a5a6",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=32,
            command=lambda: self.ativar_servir_dia(None)
        )
        btn_avulso.grid(row=2, column=0, sticky="ew", padx=15, pady=12)

        # Se for líder, cria o frame de estações conectadas na coluna esquerda
        if self.network_mode == "lider":
            self.frame_rede_lider = ctk.CTkFrame(frame_esquerda, fg_color="#141414", corner_radius=8, border_width=1, border_color="#2b2b2b")
            self.frame_rede_lider.grid(row=3, column=0, sticky="ew", padx=15, pady=(0, 12))
            
            lbl_rede_titulo = ctk.CTkLabel(self.frame_rede_lider, text="📡 Estações Conectadas (LAN)", font=ctk.CTkFont(size=12, weight="bold"), text_color="#3498db")
            lbl_rede_titulo.pack(anchor="w", padx=10, pady=(8, 2))
            
            self.lbl_rede_status = ctk.CTkLabel(self.frame_rede_lider, text=f"IP: {obter_ip_local()}:{self.local_port} | 🟢 Ativo", font=ctk.CTkFont(size=11), text_color="gray")
            self.lbl_rede_status.pack(anchor="w", padx=10)
            
            btn_reiniciar_rede = ctk.CTkButton(
                self.frame_rede_lider,
                text="🔄 Reiniciar Rede",
                font=ctk.CTkFont(size=10, weight="bold"),
                height=22,
                fg_color="#34495e",
                hover_color="#2c3e50",
                command=self.reiniciar_rede_botao
            )
            btn_reiniciar_rede.pack(anchor="w", padx=10, pady=(4, 4))
            
            self.scroll_auxiliares = ctk.CTkScrollableFrame(self.frame_rede_lider, height=80, fg_color="transparent")
            self.scroll_auxiliares.pack(fill="x", padx=5, pady=5)
            self.atualizar_lista_auxiliares_ui()
        
        # --- COLUNA DIREITA: CRIAR OU SINCRONIZAR DIA DO SERVIR ---
        frame_direita = ctk.CTkFrame(frame_corpo, fg_color="#1a1a1a", corner_radius=12, border_width=1, border_color="#2b2b2b")
        frame_direita.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        frame_direita.grid_columnconfigure(0, weight=1)
        frame_direita.grid_rowconfigure(0, weight=0)
        frame_direita.grid_rowconfigure(1, weight=0)
        frame_direita.grid_rowconfigure(2, weight=1)
        
        # Segmented Button para alternar modo de rede
        self.segmented_rede = ctk.CTkSegmentedButton(
            frame_direita, 
            values=["Líder (Host)", "Auxiliar (Estação)"],
            command=self.mudar_modo_rede
        )
        self.segmented_rede.set("Líder (Host)" if self.network_mode == "lider" else "Auxiliar (Estação)")
        self.segmented_rede.grid(row=0, column=0, sticky="ew", padx=15, pady=(15, 5))
        
        self.lbl_dir_titulo = ctk.CTkLabel(
            frame_direita, 
            text="Criar Novo Dia do Servir" if self.network_mode == "lider" else "Sincronizar via Rede Local", 
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#2ecc71" if self.network_mode == "lider" else "#3498db"
        )
        self.lbl_dir_titulo.grid(row=1, column=0, sticky="w", padx=15, pady=(5, 5))
        
        if self.network_mode == "lider":
            # Scrollable Frame para o formulário
            scroll_form = ctk.CTkScrollableFrame(frame_direita, fg_color="transparent")
            scroll_form.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
            scroll_form.grid_columnconfigure(0, weight=1)
            
            # 1. Nome do Servir
            lbl_nome_servir = ctk.CTkLabel(scroll_form, text="Nome do Servir:", font=ctk.CTkFont(weight="bold"))
            lbl_nome_servir.pack(anchor="w", padx=10, pady=(15, 2))
            self.entry_nome_servir = ctk.CTkEntry(scroll_form, placeholder_text="Ex: Culto de Domingo - 19/07")
            self.entry_nome_servir.pack(fill="x", padx=10, pady=(0, 10))
            
            # 2. Voluntários (Fotógrafos)
            lbl_voluntarios = ctk.CTkLabel(scroll_form, text="Voluntários (Fotógrafos):", font=ctk.CTkFont(weight="bold"))
            lbl_voluntarios.pack(anchor="w", padx=10, pady=(5, 2))
            
            frame_add_vol = ctk.CTkFrame(scroll_form, fg_color="transparent")
            frame_add_vol.pack(fill="x", padx=10, pady=(0, 5))
            frame_add_vol.grid_columnconfigure(0, weight=1)
            
            self.entry_add_vol = ctk.CTkEntry(frame_add_vol, placeholder_text="Nome do voluntário...")
            self.entry_add_vol.grid(row=0, column=0, sticky="ew", padx=(0, 5))
            self.entry_add_vol.bind("<Return>", lambda e: self.adicionar_voluntario_lista())
            
            btn_add_vol = ctk.CTkButton(
                frame_add_vol, 
                text="+", 
                width=30, 
                font=ctk.CTkFont(weight="bold"), 
                command=self.adicionar_voluntario_lista
            )
            btn_add_vol.grid(row=0, column=1, sticky="e")
            
            # Container para a lista de voluntários adicionados
            self.lista_voluntarios_temp = []
            self.frame_lista_vol = ctk.CTkScrollableFrame(scroll_form, height=65, fg_color="#111")
            self.frame_lista_vol.pack(fill="x", padx=10, pady=(0, 10))
            self.atualizar_lista_vol_ui()
            
            # 3. Pastas Predefinidas
            lbl_pastas = ctk.CTkLabel(scroll_form, text="Pastas Predefinidas (Categorias):", font=ctk.CTkFont(weight="bold"))
            lbl_pastas.pack(anchor="w", padx=10, pady=(5, 2))
            
            frame_add_pasta = ctk.CTkFrame(scroll_form, fg_color="transparent")
            frame_add_pasta.pack(fill="x", padx=10, pady=(0, 5))
            frame_add_pasta.grid_columnconfigure(0, weight=1)
            
            self.entry_add_pasta = ctk.CTkEntry(frame_add_pasta, placeholder_text="Ex: voltz, burn, bold...")
            self.entry_add_pasta.grid(row=0, column=0, sticky="ew", padx=(0, 5))
            self.entry_add_pasta.bind("<Return>", lambda e: self.adicionar_pasta_lista())
            
            btn_add_pasta = ctk.CTkButton(
                frame_add_pasta, 
                text="+", 
                width=30, 
                font=ctk.CTkFont(weight="bold"), 
                command=self.adicionar_pasta_lista
            )
            btn_add_pasta.grid(row=0, column=1, sticky="e")
            
            # Container para a lista de pastas adicionadas
            self.lista_pastas_temp = []
            self.frame_lista_pastas = ctk.CTkScrollableFrame(scroll_form, height=65, fg_color="#111")
            self.frame_lista_pastas.pack(fill="x", padx=10, pady=(0, 10))
            self.atualizar_lista_pastas_ui()
            
            # 3.5. Pasta do Computador (Local)
            lbl_local_titulo = ctk.CTkLabel(scroll_form, text="Pasta do Computador (Opcional):", font=ctk.CTkFont(weight="bold", size=13), text_color="#2ecc71")
            lbl_local_titulo.pack(anchor="w", padx=10, pady=(10, 2))
            
            frame_local_path = ctk.CTkFrame(scroll_form, fg_color="transparent")
            frame_local_path.pack(fill="x", padx=10, pady=(0, 10))
            frame_local_path.grid_columnconfigure(0, weight=1)
            
            self.entry_local_path_servir = ctk.CTkEntry(frame_local_path, textvariable=self.local_path_temp, placeholder_text="Pasta padrão do sistema (Fotos_Sistema)")
            self.entry_local_path_servir.grid(row=0, column=0, sticky="ew", padx=(0, 5))
            
            btn_procurar_local_servir = ctk.CTkButton(
                frame_local_path,
                text="Procurar...",
                width=80,
                command=self.selecionar_destino_servir
            )
            btn_procurar_local_servir.grid(row=0, column=1, sticky="e")
            
            # 4. Google Drive
            lbl_drive_titulo = ctk.CTkLabel(scroll_form, text="Google Drive (Opcional):", font=ctk.CTkFont(weight="bold", size=13), text_color="#3498db")
            lbl_drive_titulo.pack(anchor="w", padx=10, pady=(10, 2))
            
            lbl_drive_link = ctk.CTkLabel(scroll_form, text="Link/ID da Pasta do Drive:")
            lbl_drive_link.pack(anchor="w", padx=10)
            
            frame_drive_link = ctk.CTkFrame(scroll_form, fg_color="transparent")
            frame_drive_link.pack(fill="x", padx=10, pady=(0, 5))
            frame_drive_link.grid_columnconfigure(0, weight=1)
            
            self.entry_drive_link_servir = ctk.CTkEntry(frame_drive_link, placeholder_text="Cole o link ou ID da pasta do Drive...")
            self.entry_drive_link_servir.grid(row=0, column=0, sticky="ew", padx=(0, 5))
            
            btn_buscar_nome = ctk.CTkButton(
                frame_drive_link, 
                text="Buscar Nome", 
                width=90, 
                command=self.buscar_nome_drive_thread
            )
            btn_buscar_nome.grid(row=0, column=1, sticky="e")
            
            lbl_drive_nome = ctk.CTkLabel(scroll_form, text="Nome de Exibição da Pasta:")
            lbl_drive_nome.pack(anchor="w", padx=10)
            
            frame_drive_nome_add = ctk.CTkFrame(scroll_form, fg_color="transparent")
            frame_drive_nome_add.pack(fill="x", padx=10, pady=(0, 5))
            frame_drive_nome_add.grid_columnconfigure(0, weight=1)
            
            self.entry_drive_nome_servir = ctk.CTkEntry(frame_drive_nome_add, placeholder_text="Nome da Pasta (busca automática ou digite)")
            self.entry_drive_nome_servir.grid(row=0, column=0, sticky="ew", padx=(0, 5))
            self.entry_drive_nome_servir.bind("<Return>", lambda e: self.adicionar_drive_lista())
            
            btn_add_drive = ctk.CTkButton(
                frame_drive_nome_add, 
                text="+ Add Pasta", 
                width=90, 
                font=ctk.CTkFont(weight="bold"), 
                command=self.adicionar_drive_lista
            )
            btn_add_drive.grid(row=0, column=1, sticky="e")
            
            # Container para a lista de pastas do Drive adicionadas
            self.frame_lista_drive = ctk.CTkScrollableFrame(scroll_form, height=65, fg_color="#111")
            self.frame_lista_drive.pack(fill="x", padx=10, pady=(0, 15))
            self.atualizar_lista_drive_ui()
            
            # Botão Criar
            self.btn_criar_servir = ctk.CTkButton(
                scroll_form, 
                text="🚀 Criar e Ativar Novo Servir", 
                font=ctk.CTkFont(size=14, weight="bold"),
                fg_color="#2ecc71", 
                hover_color="#27ae60",
                height=40,
                command=self.criar_novo_servir
            )
            self.btn_criar_servir.pack(fill="x", padx=10, pady=(5, 10))
        else:
            self.frame_sync_auxiliar = ctk.CTkFrame(frame_direita, fg_color="transparent")
            self.frame_sync_auxiliar.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
            
            lbl_info = ctk.CTkLabel(
                self.frame_sync_auxiliar, 
                text="Esta estação receberá o preset (voluntários e categorias)\ndo computador Líder automaticamente.",
                font=ctk.CTkFont(size=12),
                justify="center"
            )
            lbl_info.pack(pady=(20, 15))
            
            self.frame_status_busca = ctk.CTkFrame(self.frame_sync_auxiliar, fg_color="#141414", corner_radius=8, border_width=1, border_color="#2b2b2b")
            self.frame_status_busca.pack(fill="x", padx=15, pady=10)
            
            self.lbl_status_busca = ctk.CTkLabel(
                self.frame_status_busca, 
                text="🔍 Procurando Líder na rede local...",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="orange"
            )
            self.lbl_status_busca.pack(pady=15)
            
            self.frame_dados_lider = ctk.CTkFrame(self.frame_sync_auxiliar, fg_color="transparent")
            
            self.lbl_lider_nome = ctk.CTkLabel(self.frame_dados_lider, text="Evento: --", font=ctk.CTkFont(size=14, weight="bold"))
            self.lbl_lider_nome.pack(pady=2)
            
            self.lbl_lider_ip = ctk.CTkLabel(self.frame_dados_lider, text="Líder IP: --", font=ctk.CTkFont(size=12), text_color="gray")
            self.lbl_lider_ip.pack(pady=2)
            
            self.btn_sincronizar = ctk.CTkButton(
                self.frame_sync_auxiliar,
                text="🔗 Sincronizar e Iniciar Importação",
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color="#2ecc71",
                hover_color="#27ae60",
                height=38,
                command=self.conectar_e_sincronizar_lider
            )
            self.btn_sincronizar.configure(state="disabled")
            self.btn_sincronizar.pack(fill="x", padx=15, pady=15)
            
            self.btn_reiniciar_busca = ctk.CTkButton(
                self.frame_sync_auxiliar,
                text="🔄 Reiniciar Busca",
                font=ctk.CTkFont(size=11, weight="bold"),
                height=28,
                fg_color="#34495e",
                hover_color="#2c3e50",
                command=self.reiniciar_rede_botao
            )
            self.btn_reiniciar_busca.pack(fill="x", padx=15, pady=(0, 10))
            
            self.atualizar_lider_detectado_ui()
            
        # Carrega e exibe a lista de dias passados
        self.dias_servir = self.carregar_dias_servir()
        self.atualizar_lista_dias_ui()

    def adicionar_voluntario_lista(self, event=None):
        nome = self.entry_add_vol.get().strip()
        if nome:
            if nome not in self.lista_voluntarios_temp:
                self.lista_voluntarios_temp.append(nome)
                self.entry_add_vol.delete(0, 'end')
                self.atualizar_lista_vol_ui()
            else:
                messagebox.showwarning("Aviso", f"O voluntário '{nome}' já foi adicionado!")

    def remover_voluntario_lista(self, nome):
        if nome in self.lista_voluntarios_temp:
            self.lista_voluntarios_temp.remove(nome)
            self.atualizar_lista_vol_ui()

    def atualizar_lista_vol_ui(self):
        for widget in self.frame_lista_vol.winfo_children():
            widget.destroy()
            
        if not self.lista_voluntarios_temp:
            lbl_vazio = ctk.CTkLabel(self.frame_lista_vol, text="Nenhum voluntário adicionado.", text_color="gray", font=ctk.CTkFont(size=12))
            lbl_vazio.pack(pady=10)
            return
            
        for vol in self.lista_voluntarios_temp:
            frame_item = ctk.CTkFrame(self.frame_lista_vol, fg_color="#222")
            frame_item.pack(fill="x", pady=2, padx=5)
            
            lbl_nome = ctk.CTkLabel(frame_item, text=vol, anchor="w")
            lbl_nome.pack(side="left", padx=10, fill="x", expand=True)
            
            btn_del = ctk.CTkButton(
                frame_item, 
                text="❌", 
                width=24, 
                height=20, 
                fg_color="transparent", 
                hover_color="#e74c3c", 
                command=lambda v=vol: self.remover_voluntario_lista(v)
            )
            btn_del.pack(side="right", padx=5)

    def adicionar_pasta_lista(self, event=None):
        pasta = self.entry_add_pasta.get().strip()
        if pasta:
            # Substitui barras por nada para garantir segurança de nome de pasta
            for char in ['/', '\\\\', ':', '*', '?', '"', '<', '>', '|']:
                pasta = pasta.replace(char, '')
            if pasta:
                if pasta not in self.lista_pastas_temp:
                    self.lista_pastas_temp.append(pasta)
                    self.entry_add_pasta.delete(0, 'end')
                    self.atualizar_lista_pastas_ui()
                else:
                    messagebox.showwarning("Aviso", f"A pasta '{pasta}' já foi adicionada!")

    def remover_pasta_lista(self, pasta):
        if pasta in self.lista_pastas_temp:
            self.lista_pastas_temp.remove(pasta)
            self.atualizar_lista_pastas_ui()

    def atualizar_lista_pastas_ui(self):
        for widget in self.frame_lista_pastas.winfo_children():
            widget.destroy()
            
        if not self.lista_pastas_temp:
            lbl_vazio = ctk.CTkLabel(self.frame_lista_pastas, text="Nenhuma pasta adicionada.", text_color="gray", font=ctk.CTkFont(size=12))
            lbl_vazio.pack(pady=10)
            return
            
        for pasta in self.lista_pastas_temp:
            frame_item = ctk.CTkFrame(self.frame_lista_pastas, fg_color="#222")
            frame_item.pack(fill="x", pady=2, padx=5)
            
            lbl_nome = ctk.CTkLabel(frame_item, text=pasta, anchor="w")
            lbl_nome.pack(side="left", padx=10, fill="x", expand=True)
            
            btn_del = ctk.CTkButton(
                frame_item, 
                text="❌", 
                width=24, 
                height=20, 
                fg_color="transparent", 
                hover_color="#e74c3c", 
                command=lambda p=pasta: self.remover_pasta_lista(p)
            )
            btn_del.pack(side="right", padx=5)

    def selecionar_destino_servir(self):
        pasta = filedialog.askdirectory(title="Selecione a pasta do computador para este Servir")
        if pasta:
            self.local_path_temp.set(pasta)

    def adicionar_drive_lista(self, event=None):
        link = self.entry_drive_link_servir.get().strip()
        nome = self.entry_drive_nome_servir.get().strip()
        if not link:
            messagebox.showwarning("Aviso", "Insira o link ou ID da pasta do Google Drive!")
            return
        if not nome:
            nome = "Pasta do Google Drive"
            
        # Verifica se já está adicionada
        for item in self.lista_drive_temp:
            if item['link'] == link:
                messagebox.showwarning("Aviso", "Esta pasta do Google Drive já foi adicionada!")
                return
                
        self.lista_drive_temp.append({"link": link, "nome": nome})
        self.entry_drive_link_servir.delete(0, 'end')
        self.entry_drive_nome_servir.delete(0, 'end')
        self.atualizar_lista_drive_ui()

    def remover_drive_lista(self, index):
        if 0 <= index < len(self.lista_drive_temp):
            self.lista_drive_temp.pop(index)
            self.atualizar_lista_drive_ui()

    def atualizar_lista_drive_ui(self):
        for widget in self.frame_lista_drive.winfo_children():
            widget.destroy()
            
        if not self.lista_drive_temp:
            lbl_vazio = ctk.CTkLabel(self.frame_lista_drive, text="Nenhuma pasta do Drive adicionada.", text_color="gray", font=ctk.CTkFont(size=12))
            lbl_vazio.pack(pady=10)
            return
            
        for i, item in enumerate(self.lista_drive_temp):
            frame_item = ctk.CTkFrame(self.frame_lista_drive, fg_color="#222")
            frame_item.pack(fill="x", pady=2, padx=5)
            
            lbl_nome = ctk.CTkLabel(frame_item, text=item['nome'], anchor="w")
            lbl_nome.pack(side="left", padx=10, fill="x", expand=True)
            
            # Use default argument binding to prevent index closure binding bug
            btn_del = ctk.CTkButton(
                frame_item, 
                text="❌", 
                width=24, 
                height=20, 
                fg_color="transparent", 
                hover_color="#e74c3c", 
                command=lambda idx=i: self.remover_drive_lista(idx)
            )
            btn_del.pack(side="right", padx=5)

    def buscar_nome_drive_thread(self):
        link = self.entry_drive_link_servir.get().strip()
        if not link:
            messagebox.showwarning("Aviso", "Insira o link ou ID da pasta do Google Drive primeiro!")
            return
            
        def buscar():
            self.entry_drive_nome_servir.configure(state="normal")
            self.entry_drive_nome_servir.delete(0, 'end')
            self.entry_drive_nome_servir.insert(0, "Buscando nome no Drive...")
            self.entry_drive_nome_servir.configure(state="disabled")
            
            nome = self.obter_nome_pasta_drive_servir(link)
            
            self.entry_drive_nome_servir.configure(state="normal")
            self.entry_drive_nome_servir.delete(0, 'end')
            if nome:
                self.entry_drive_nome_servir.insert(0, nome)
            else:
                self.entry_drive_nome_servir.insert(0, "")
                messagebox.showwarning(
                    "Aviso", 
                    "Não foi possível obter o nome da pasta. Certifique-se de que está autenticado e o link é válido, ou digite o nome manualmente."
                )
                
        threading.Thread(target=buscar, daemon=True).start()

    def obter_nome_pasta_drive_servir(self, link_ou_id):
        if not GOOGLE_DRIVE_DISPONIVEL:
            return None
        folder_id = self.extrair_id_pasta_drive(link_ou_id)
        if folder_id == 'root':
            return "Raiz do Google Drive"
            
        caminho_credenciais = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")
        if not os.path.exists(caminho_credenciais):
            return None
            
        SCOPES = ['https://www.googleapis.com/auth/drive']
        token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'token.json')
        creds = None
        if os.path.exists(token_path):
            try:
                creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            except Exception:
                pass
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    return None
            else:
                return None
            
        try:
            service = build('drive', 'v3', credentials=creds)
            pasta_meta = service.files().get(fileId=folder_id, fields='name').execute()
            return pasta_meta.get('name')
        except Exception as e:
            print(f"Erro ao obter nome da pasta no Drive: {e}")
            return None

    def criar_novo_servir(self):
        if self.servir_em_edicao:
            self.salvar_edicao_servir()
            return

        nome_servir = self.entry_nome_servir.get().strip()
        if not nome_servir:
            messagebox.showwarning("Aviso", "Por favor, insira o nome do Servir!")
            return
            
        for char in ['/', '\\\\', ':', '*', '?', '"', '<', '>', '|']:
            if char in nome_servir:
                messagebox.showwarning("Aviso", f"O nome do Servir não pode conter o caractere '{char}'!")
                return
                
        if not self.lista_voluntarios_temp:
            messagebox.showwarning("Aviso", "Por favor, adicione pelo menos um voluntário!")
            return
            
        # Se preencheu os campos do Drive mas não clicou em adicionar
        drive_link = self.entry_drive_link_servir.get().strip()
        drive_nome = self.entry_drive_nome_servir.get().strip()
        if drive_link:
            if not drive_nome:
                drive_nome = "Pasta do Google Drive"
            if not any(item['link'] == drive_link for item in self.lista_drive_temp):
                self.lista_drive_temp.append({"link": drive_link, "nome": drive_nome})

        primeiro_link = self.lista_drive_temp[0]['link'] if self.lista_drive_temp else ""
        primeiro_nome = self.lista_drive_temp[0]['nome'] if self.lista_drive_temp else ""

        local_path = self.local_path_temp.get().strip()
        local_nome = os.path.basename(local_path) if local_path else ""

        novo_servir = {
            "id": str(int(time.time())),
            "nome": nome_servir,
            "data_criacao": date.today().isoformat(),
            "voluntarios": self.lista_voluntarios_temp.copy(),
            "pastas_predefinidas": self.lista_pastas_temp.copy(),
            "drive_link": primeiro_link,
            "drive_nome": primeiro_nome,
            "drive_folders": self.lista_drive_temp.copy(),
            "local_path": local_path,
            "local_nome": local_nome
        }
        
        self.dias_servir.append(novo_servir)
        self.salvar_dias_servir(self.dias_servir)
        
        # Pré-cria a estrutura de pastas localmente assim que o servir é criado (apenas as categorias)
        bases_criar = [self.destino_padrao_app]
        if local_path:
            bases_criar.append(local_path)
        for p in self.pastas_local:
            bases_criar.append(p['caminho'])
            
        for base in bases_criar:
            if not base:
                continue
            base_servir = os.path.join(base, nome_servir)
            os.makedirs(base_servir, exist_ok=True)
            pastas_cats = novo_servir.get("pastas_predefinidas", [])
            for cat in pastas_cats:
                os.makedirs(os.path.join(base_servir, cat), exist_ok=True)
        
        # Limpa o formulário
        self.entry_nome_servir.delete(0, 'end')
        self.entry_drive_link_servir.delete(0, 'end')
        self.entry_drive_nome_servir.delete(0, 'end')
        self.lista_voluntarios_temp.clear()
        self.lista_pastas_temp.clear()
        self.lista_drive_temp.clear()
        self.local_path_temp.set("")
        self.atualizar_lista_vol_ui()
        self.atualizar_lista_pastas_ui()
        self.atualizar_lista_drive_ui()
        
        self.atualizar_lista_dias_ui()
        
        # Ativa o servir recém criado
        self.ativar_servir_dia(novo_servir)

    def editar_servir_dia(self, servir):
        self.servir_em_edicao = servir
        
        # Altera o título do formulário para indicar Edição
        self.lbl_dir_titulo.configure(text=f"✏️ Editar Servir: {servir.get('nome')}", text_color="#3498db")
        
        # Preenche os campos do formulário
        self.entry_nome_servir.delete(0, 'end')
        self.entry_nome_servir.insert(0, servir.get('nome', ''))
        
        self.lista_voluntarios_temp = servir.get('voluntarios', []).copy()
        self.atualizar_lista_vol_ui()
        
        self.lista_pastas_temp = servir.get('pastas_predefinidas', []).copy()
        self.atualizar_lista_pastas_ui()
        
        self.entry_drive_link_servir.delete(0, 'end')
        self.entry_drive_link_servir.insert(0, servir.get('drive_link', ''))
        
        self.entry_drive_nome_servir.delete(0, 'end')
        self.entry_drive_nome_servir.insert(0, servir.get('drive_nome', ''))
        
        # Carrega pasta local
        self.local_path_temp.set(servir.get('local_path', ''))

        # Carrega a lista de pastas do Drive
        drive_folders = servir.get('drive_folders', [])
        if not drive_folders and servir.get('drive_link'):
            drive_folders = [{"link": servir.get('drive_link'), "nome": servir.get('drive_nome', 'Pasta do Google Drive')}]
        self.lista_drive_temp = drive_folders.copy()
        self.atualizar_lista_drive_ui()
        
        # Altera o botão de ação principal
        self.btn_criar_servir.configure(
            text="💾 Salvar Alterações",
            fg_color="#3498db",
            hover_color="#2980b9"
        )
        
        # Mostra o botão Cancelar se não existir
        if not hasattr(self, 'btn_cancelar_edicao') or not self.btn_cancelar_edicao.winfo_exists():
            self.btn_cancelar_edicao = ctk.CTkButton(
                self.btn_criar_servir.master,
                text="❌ Cancelar Edição",
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="#7f8c8d",
                hover_color="#95a5a6",
                height=32,
                command=self.cancelar_edicao_servir
            )
            self.btn_cancelar_edicao.pack(fill="x", padx=10, pady=(5, 10))

    def cancelar_edicao_servir(self):
        self.servir_em_edicao = None
        
        # Restaura título do formulário
        self.lbl_dir_titulo.configure(text="Criar Novo Dia do Servir", text_color="#2ecc71")
        
        # Limpa os campos
        self.entry_nome_servir.delete(0, 'end')
        self.lista_voluntarios_temp = []
        self.atualizar_lista_vol_ui()
        
        self.lista_pastas_temp = []
        self.atualizar_lista_pastas_ui()
        
        self.entry_drive_link_servir.delete(0, 'end')
        self.entry_drive_nome_servir.delete(0, 'end')
        self.lista_drive_temp = []
        self.atualizar_lista_drive_ui()
        self.local_path_temp.set("")
        
        # Restaura o botão de ação principal
        self.btn_criar_servir.configure(
            text="🚀 Criar e Ativar Novo Servir",
            fg_color="#2ecc71",
            hover_color="#27ae60"
        )
        
        # Remove o botão cancelar se ele existir
        if hasattr(self, 'btn_cancelar_edicao') and self.btn_cancelar_edicao.winfo_exists():
            self.btn_cancelar_edicao.destroy()

    def salvar_edicao_servir(self):
        if not self.servir_em_edicao:
            return
            
        nome_servir = self.entry_nome_servir.get().strip()
        if not nome_servir:
            messagebox.showwarning("Aviso", "Por favor, insira o nome do Servir!")
            return
            
        for char in ['/', '\\\\', ':', '*', '?', '"', '<', '>', '|']:
            if char in nome_servir:
                messagebox.showwarning("Aviso", f"O nome do Servir não pode conter o caractere '{char}'!")
                return
                
        if not self.lista_voluntarios_temp:
            messagebox.showwarning("Aviso", "Por favor, adicione pelo menos um voluntário!")
            return
            
        # Se preencheu os campos do Drive mas não clicou em adicionar
        drive_link = self.entry_drive_link_servir.get().strip()
        drive_nome = self.entry_drive_nome_servir.get().strip()
        if drive_link:
            if not drive_nome:
                drive_nome = "Pasta do Google Drive"
            if not any(item['link'] == drive_link for item in self.lista_drive_temp):
                self.lista_drive_temp.append({"link": drive_link, "nome": drive_nome})

        primeiro_link = self.lista_drive_temp[0]['link'] if self.lista_drive_temp else ""
        primeiro_nome = self.lista_drive_temp[0]['nome'] if self.lista_drive_temp else ""

        local_path = self.local_path_temp.get().strip()
        local_nome = os.path.basename(local_path) if local_path else ""

        # Atualiza os dados no objeto servir em edicao
        for idx, servir in enumerate(self.dias_servir):
            if servir.get('id') == self.servir_em_edicao.get('id'):
                self.dias_servir[idx]['nome'] = nome_servir
                self.dias_servir[idx]['voluntarios'] = self.lista_voluntarios_temp.copy()
                self.dias_servir[idx]['pastas_predefinidas'] = self.lista_pastas_temp.copy()
                self.dias_servir[idx]['drive_link'] = primeiro_link
                self.dias_servir[idx]['drive_nome'] = primeiro_nome
                self.dias_servir[idx]['drive_folders'] = self.lista_drive_temp.copy()
                self.dias_servir[idx]['local_path'] = local_path
                self.dias_servir[idx]['local_nome'] = local_nome
                
        # Salva no arquivo
        self.salvar_dias_servir(self.dias_servir)
        
        # Se adicionou novas pastas de categoria, pré-criamos a estrutura de pastas localmente
        bases_criar = [self.destino_padrao_app]
        if local_path:
            bases_criar.append(local_path)
        for p in self.pastas_local:
            bases_criar.append(p['caminho'])
            
        for base in bases_criar:
            if not base:
                continue
            base_servir = os.path.join(base, nome_servir)
            os.makedirs(base_servir, exist_ok=True)
            for cat in self.lista_pastas_temp:
                os.makedirs(os.path.join(base_servir, cat), exist_ok=True)
                
        # Limpa o formulário e encerra a edição
        self.servir_em_edicao = None
        
        self.entry_nome_servir.delete(0, 'end')
        self.entry_drive_link_servir.delete(0, 'end')
        self.entry_drive_nome_servir.delete(0, 'end')
        self.lista_voluntarios_temp.clear()
        self.lista_pastas_temp.clear()
        self.lista_drive_temp.clear()
        self.local_path_temp.set("")
        self.atualizar_lista_vol_ui()
        self.atualizar_lista_pastas_ui()
        self.atualizar_lista_drive_ui()
        
        # Restaura título do formulário
        self.lbl_dir_titulo.configure(text="Criar Novo Dia do Servir", text_color="#2ecc71")
        
        # Restaura o botão de ação principal
        self.btn_criar_servir.configure(
            text="🚀 Criar e Ativar Novo Servir",
            fg_color="#2ecc71",
            hover_color="#27ae60"
        )
        
        # Remove o botão cancelar se ele existir
        if hasattr(self, 'btn_cancelar_edicao') and self.btn_cancelar_edicao.winfo_exists():
            self.btn_cancelar_edicao.destroy()
            
        self.atualizar_lista_dias_ui()
        messagebox.showinfo("Sucesso", "Dia do Servir editado com sucesso!")

    def atualizar_lista_dias_ui(self):
        for widget in self.scroll_dias.winfo_children():
            widget.destroy()
            
        if not self.dias_servir:
            lbl_vazio = ctk.CTkLabel(
                self.scroll_dias, 
                text="Nenhum dia de servir cadastrado.\n\nPreencha o formulário ao lado para começar!", 
                text_color="gray",
                font=ctk.CTkFont(size=12)
            )
            lbl_vazio.pack(pady=40)
            return
            
        for servir in reversed(self.dias_servir):
            frame_item = ctk.CTkFrame(self.scroll_dias, fg_color="#2b2b2b", corner_radius=8, border_width=1, border_color="#3a3a3a")
            frame_item.pack(fill="x", pady=6, padx=5)
            
            data_formatada = servir.get("data_criacao", "")
            try:
                partes = data_formatada.split("-")
                if len(partes) == 3:
                    data_formatada = f"{partes[2]}/{partes[1]}/{partes[0]}"
            except Exception:
                pass
                
            voluntarios_str = ", ".join(servir.get("voluntarios", []))
            pastas_str = ", ".join(servir.get("pastas_predefinidas", []))
            if not pastas_str:
                pastas_str = "(Nenhuma pasta configurada)"
                
            drive_str = f"☁️ Drive: {servir.get('drive_nome')}" if servir.get("drive_link") else "☁️ Sem Google Drive configurado"
            
            texto_info = (
                f"📅 {data_formatada} | {servir.get('nome')}\n"
                f"👥 Voluntários: {voluntarios_str}\n"
                f"📁 Pastas: {pastas_str}\n"
                f"{drive_str}"
            )
            
            lbl_info = ctk.CTkLabel(
                frame_item, 
                text=texto_info, 
                font=ctk.CTkFont(size=11),
                justify="left",
                anchor="w"
            )
            lbl_info.pack(fill="x", padx=12, pady=(10, 5))
            
            # Sub-frame de ações
            frame_acoes = ctk.CTkFrame(frame_item, fg_color="transparent")
            frame_acoes.pack(fill="x", padx=12, pady=(0, 10))
            
            btn_entrar = ctk.CTkButton(
                frame_acoes, 
                text="▶ Iniciar Importação", 
                fg_color="#2ecc71", 
                hover_color="#27ae60",
                font=ctk.CTkFont(size=11, weight="bold"),
                height=26,
                command=lambda s=servir: self.ativar_servir_dia(s)
            )
            btn_entrar.pack(side="left", fill="x", expand=True, padx=(0, 4))
            
            btn_editar = ctk.CTkButton(
                frame_acoes, 
                text="✏️ Editar", 
                fg_color="#3498db", 
                hover_color="#2980b9",
                font=ctk.CTkFont(size=11, weight="bold"),
                width=65,
                height=26,
                command=lambda s=servir: self.editar_servir_dia(s)
            )
            btn_editar.pack(side="left", padx=(0, 4))
            
            btn_excluir = ctk.CTkButton(
                frame_acoes, 
                text="🗑️ Excluir", 
                fg_color="#e74c3c", 
                hover_color="#c0392b",
                font=ctk.CTkFont(size=11, weight="bold"),
                width=65,
                height=26,
                command=lambda s=servir: self.excluir_servir_dia(s)
            )
            btn_excluir.pack(side="right")

    def excluir_servir_dia(self, servir):
        confirmar = messagebox.askyesno(
            "Confirmar Exclusão", 
            f"Deseja realmente excluir a configuração do dia de servir '{servir.get('nome')}'?\n\n"
            "Esta ação apagará apenas esta configuração no painel, sem apagar nenhuma foto salva."
        )
        if confirmar:
            self.dias_servir = [d for d in self.dias_servir if d.get('id') != servir.get('id')]
            self.salvar_dias_servir(self.dias_servir)
            self.atualizar_lista_dias_ui()

    def ativar_servir_dia(self, servir):
        self.active_servir = servir
        if servir:
            nome_servir = servir.get('nome')
            
            # Se o evento possui uma pasta local específica configurada, ativa ela como destino!
            local_path = servir.get('local_path')
            if local_path:
                self.destino_path.set(local_path)
            else:
                self.destino_path.set(self.destino_padrao_app)
                
            bases_criar = []
            
            destino_base = self.destino_path.get()
            if destino_base:
                bases_criar.append(destino_base)
                
            if hasattr(self, 'destino_padrao_app') and self.destino_padrao_app:
                if self.destino_padrao_app not in bases_criar:
                    bases_criar.append(self.destino_padrao_app)
                    
            if hasattr(self, 'pastas_local') and self.pastas_local:
                for p in self.pastas_local:
                    caminho = p.get('caminho')
                    if caminho and caminho not in bases_criar:
                        bases_criar.append(caminho)
                        
            for base in bases_criar:
                if not base:
                    continue
                base_servir = os.path.join(base, nome_servir)
                try:
                    os.makedirs(base_servir, exist_ok=True)
                    pastas_cats = servir.get("pastas_predefinidas", [])
                    for cat in pastas_cats:
                        os.makedirs(os.path.join(base_servir, cat), exist_ok=True)
                except Exception as e:
                    print(f"Erro ao criar estrutura de pastas em {base}: {e}")
                    
        self.mostrar_tela_descarregamento()

    # --- TELA DE DESCARREGAMENTO ---
    def mostrar_tela_descarregamento(self):
        for widget in self.winfo_children():
            if widget != self.monitor_thread:
                try:
                    widget.pack_forget()
                    widget.grid_forget()
                    widget.destroy()
                except Exception:
                    pass
                    
        self.geometry("750x820")
        self.minsize(750, 820)
        
        self.container_principal = ctk.CTkFrame(self, fg_color="transparent")
        self.container_principal.pack(fill="both", expand=True, padx=25, pady=15)
        
        # 1. HEADER FRAME
        self.frame_header = ctk.CTkFrame(self.container_principal, fg_color="transparent")
        self.frame_header.pack(fill="x", pady=(0, 5))
        
        self.frame_header.grid_columnconfigure(0, weight=0)
        self.frame_header.grid_columnconfigure(1, weight=1)
        self.frame_header.grid_columnconfigure(2, weight=0)

        # Botão Voltar ao Painel
        self.btn_voltar = ctk.CTkButton(
            self.frame_header, 
            text="⬅ Voltar", 
            font=ctk.CTkFont(size=11, weight="bold"), 
            height=26, 
            width=70,
            fg_color="#34495e", 
            hover_color="#2c3e50", 
            command=self.mostrar_pagina_inicial
        )
        self.btn_voltar.grid(row=0, column=0, sticky="w")

        # Título central
        self.lbl_titulo = ctk.CTkLabel(
            self.frame_header, 
            text="Descarregador de Fotos", 
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.lbl_titulo.grid(row=0, column=1, sticky="nsew")

        # Indicador de Servir Ativo ou Modo Avulso
        self.frame_status_servir = ctk.CTkFrame(self.frame_header, fg_color="transparent")
        self.frame_status_servir.grid(row=0, column=2, sticky="e")
        
        if self.active_servir:
            lbl_servir_nome = ctk.CTkLabel(
                self.frame_status_servir, 
                text=f"Servir: {self.active_servir.get('nome')}", 
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#2ecc71"
            )
            lbl_servir_nome.pack(side="left", padx=5)
            
            # Indicador de rede local
            if self.network_mode == "auxiliar":
                lbl_rede = ctk.CTkLabel(
                    self.frame_status_servir, 
                    text="📡 Auxiliar", 
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#3498db"
                )
                lbl_rede.pack(side="left", padx=5)
            
            self.btn_abrir_raiz = ctk.CTkButton(
                self.frame_status_servir,
                text="📂 Abrir Pasta do Servir",
                font=ctk.CTkFont(size=11, weight="bold"),
                height=26,
                fg_color="#34495e",
                hover_color="#2c3e50",
                command=self.abrir_pasta_raiz_servir
            )
            self.btn_abrir_raiz.pack(side="left", padx=5)

            if self.network_mode == "lider":
                self.btn_finalizar_servir = ctk.CTkButton(
                    self.frame_status_servir,
                    text="🏁 Finalizar Servir",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    height=26,
                    fg_color="#d35400",
                    hover_color="#e67e22",
                    command=self.finalizar_servir_thread
                )
                self.btn_finalizar_servir.pack(side="left", padx=5)
            else:
                self.btn_finalizar_servir = ctk.CTkButton(
                    self.frame_status_servir,
                    text="🔒 Finalizar (Líder)",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    height=26,
                    fg_color="#555555",
                    state="disabled"
                )
                self.btn_finalizar_servir.pack(side="left", padx=5)
        else:
            lbl_servir_nome = ctk.CTkLabel(
                self.frame_status_servir, 
                text="Modo Avulso", 
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#e67e22"
            )
            lbl_servir_nome.pack(side="right")

        # 2. STATUS DO CARTÃO SD
        self.lbl_status = ctk.CTkLabel(
            self.container_principal, 
            text="Aguardando inserção do Cartão SD...", 
            text_color="orange", 
            font=ctk.CTkFont(size=12)
        )
        self.lbl_status.pack(pady=(0, 6))

        # 3. SELEÇÃO DO FOTÓGRAFO
        if self.active_servir:
            self.lbl_nome = ctk.CTkLabel(self.container_principal, text="Selecione o Fotógrafo (Voluntário):", font=ctk.CTkFont(weight="bold"))
            self.lbl_nome.pack(anchor="w", padx=30)
            
            vols = self.active_servir.get("voluntarios", [])
            opcoes_vols = vols.copy()
            opcoes_vols.append("Outro...")
            
            self.combo_fotografo_var = ctk.StringVar(value=opcoes_vols[0] if opcoes_vols else "Outro...")
            self.combo_fotografo = ctk.CTkOptionMenu(
                self.container_principal,
                values=opcoes_vols,
                variable=self.combo_fotografo_var,
                command=self.ao_selecionar_fotografo,
                height=28
            )
            self.combo_fotografo.pack(pady=(0, 4), padx=30, fill="x")
            
            # Campo de texto extra caso selecione "Outro..."
            self.entry_nome_outro = ctk.CTkEntry(
                self.container_principal, 
                height=28, 
                placeholder_text="Digite o nome do fotógrafo alternativo..."
            )
            self.entry_nome_outro.bind("<KeyRelease>", self.atualizar_caminho_final_exibicao)
            
            if self.combo_fotografo_var.get() == "Outro...":
                self.entry_nome_outro.pack(pady=(2, 4), padx=30, fill="x")
        else:
            self.lbl_nome = ctk.CTkLabel(self.container_principal, text="Nome do Fotógrafo:", font=ctk.CTkFont(weight="bold"))
            self.lbl_nome.pack(anchor="w", padx=30)
            
            self.entry_nome = ctk.CTkEntry(
                self.container_principal, 
                width=520, 
                height=28, 
                placeholder_text="Ex: JoaoSilva"
            )
            self.entry_nome.bind("<KeyRelease>", self.atualizar_caminho_final_exibicao)
            self.entry_nome.pack(pady=(0, 4), padx=30, fill="x")

        # 4. PASTAS NO CARTÃO SD
        self.frame_lbl_pastas = ctk.CTkFrame(self.container_principal, fg_color="transparent")
        self.frame_lbl_pastas.pack(fill="x", padx=30, pady=(4, 2))

        self.lbl_pastas = ctk.CTkLabel(self.frame_lbl_pastas, text="Pastas no Cartão SD:", font=ctk.CTkFont(weight="bold"))
        self.lbl_pastas.pack(side="left")

        self.btn_manual = ctk.CTkButton(
            self.frame_lbl_pastas, 
            text="📂 Origem Manual", 
            height=20, 
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#34495e",
            hover_color="#2c3e50",
            command=self.selecionar_origem_manual
        )
        self.btn_manual.pack(side="right")
        
        self.frame_pastas = ctk.CTkScrollableFrame(self.container_principal, width=500, height=80)
        self.frame_pastas.pack(pady=(0, 4), padx=30, fill="both", expand=True)
        
        self.lbl_vazio = ctk.CTkLabel(self.frame_pastas, text="Nenhum cartão detectado.")
        self.lbl_vazio.pack(pady=15)

        # 5. CONFIGURAÇÃO DE CATEGORIA (Somente para Servir)
        if self.active_servir:
            self.lbl_categoria = ctk.CTkLabel(self.container_principal, text="Pasta de Destino (Categoria):", font=ctk.CTkFont(weight="bold"))
            self.lbl_categoria.pack(anchor="w", padx=30, pady=(4, 0))
            
            opcoes_cat = self.active_servir.get("pastas_predefinidas", []).copy()
            opcoes_cat.append("Raiz (Nenhuma)")
            
            self.combo_categoria_var = ctk.StringVar(value=opcoes_cat[0] if opcoes_cat else "Raiz (Nenhuma)")
            self.combo_categoria = ctk.CTkOptionMenu(
                self.container_principal,
                values=opcoes_cat,
                variable=self.combo_categoria_var,
                height=28
            )
            self.combo_categoria.pack(pady=(0, 4), padx=30, fill="x")

        # 6. PASTA DE DESTINO NO COMPUTADOR
        self.destino_path.set(self.destino_padrao_app)
        
        lbl_destino = ctk.CTkLabel(self.container_principal, text="Pasta de Destino no Computador:", font=ctk.CTkFont(weight="bold"))
        lbl_destino.pack(anchor="w", padx=30, pady=(4, 2))
        
        self.combo_destino_var = ctk.StringVar(value="Pasta do Aplicativo (Padrão)")
        self.combo_destino = ctk.CTkOptionMenu(
            self.container_principal,
            values=["Pasta do Aplicativo (Padrão)"],
            variable=self.combo_destino_var,
            command=self.ao_alterar_destino_combo,
            height=28
        )
        self.combo_destino.pack(pady=(0, 4), padx=30, fill="x")
        self.recarregar_combo_destino()



        # Checkbox subpasta (Apenas Modo Avulso)
        if not self.active_servir:
            self.criar_pasta_fotografo_var = ctk.BooleanVar(value=True)
            self.chk_criar_pasta_fotografo = ctk.CTkCheckBox(self.container_principal, text="Criar subpasta local com o nome do fotógrafo", variable=self.criar_pasta_fotografo_var)
            self.chk_criar_pasta_fotografo.pack(anchor="w", padx=30, pady=(0, 4))
            
        # 7. CAMINHO FINAL RESOLVIDO
        self.lbl_caminho_final = ctk.CTkLabel(self.container_principal, text="Pasta Final de Destino (Será criada automaticamente):", font=ctk.CTkFont(weight="bold", size=12), text_color="#3498db")
        self.lbl_caminho_final.pack(anchor="w", padx=30, pady=(4, 0))
        
        self.entry_caminho_final = ctk.CTkEntry(
            self.container_principal,
            height=28,
            state="readonly",
            text_color="#2ecc71"
        )
        self.entry_caminho_final.pack(pady=(0, 6), padx=30, fill="x")

        # 8. PROGRESSO
        self.lbl_progresso = ctk.CTkLabel(self.container_principal, text="Progresso: 0%")
        self.lbl_progresso.pack(anchor="w", padx=30)
        self.progressbar = ctk.CTkProgressBar(self.container_principal, width=520, height=8)
        self.progressbar.pack(pady=(1, 6), padx=30, fill="x")
        self.progressbar.set(0)

        # 9. BOTOES DE AÇÃO
        self.frame_botoes = ctk.CTkFrame(self.container_principal, fg_color="transparent")
        self.frame_botoes.pack(pady=(2, 1), padx=30, fill="x")

        self.btn_iniciar = ctk.CTkButton(
            self.frame_botoes, 
            text="Iniciar Transferência", 
            font=ctk.CTkFont(size=13, weight="bold"), 
            height=36, 
            fg_color="green", 
            hover_color="darkgreen", 
            command=self.iniciar_transferencia
        )
        self.btn_iniciar.pack(fill="x", expand=True)

        self.frame_botoes_secundarios = ctk.CTkFrame(self.container_principal, fg_color="transparent")
        self.frame_botoes_secundarios.pack(pady=(1, 4), padx=30, fill="x")

        self.btn_selecionar = ctk.CTkButton(
            self.frame_botoes_secundarios, 
            text="🔍 Selecionar / Revisar Fotos", 
            height=36, 
            font=ctk.CTkFont(size=12, weight="bold"), 
            fg_color="#1f538d", 
            hover_color="#14375e", 
            command=self.abrir_revisor, 
            state="disabled"
        )
        self.btn_selecionar.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.btn_abrir = ctk.CTkButton(
            self.frame_botoes_secundarios, 
            text="📁 Abrir Pasta", 
            height=36, 
            font=ctk.CTkFont(size=12), 
            command=self.abrir_pasta, 
            state="disabled"
        )
        self.btn_abrir.pack(side="right", fill="x", expand=True)

        # 10. GOOGLE DRIVE SELECTION & UPLOAD
        self.lbl_drive_link = ctk.CTkLabel(self.container_principal, text="Pasta de Destino no Google Drive:")
        self.lbl_drive_link.pack(anchor="w", padx=30, pady=(2, 1))
        
        self.combo_drive_var = ctk.StringVar()
        self.combo_drive = ctk.CTkOptionMenu(
            self.container_principal, 
            values=[],
            variable=self.combo_drive_var,
            width=520,
            height=28
        )
        self.combo_drive.pack(pady=(0, 4), padx=30, fill="x")
        self.recarregar_combo_drive()

        self.btn_enviar_drive = ctk.CTkButton(
            self.container_principal, 
            text="📤 Enviar Fotos Selecionadas para o Google Drive", 
            height=36, 
            font=ctk.CTkFont(size=12, weight="bold"), 
            fg_color="#4285F4", 
            hover_color="#357ae8", 
            command=self.iniciar_upload_drive, 
            state="disabled"
        )
        self.btn_enviar_drive.pack(pady=(2, 10), padx=30, fill="x")

        # Inicia traces para reatividade
        self.iniciar_traces()
        self.atualizar_caminho_final_exibicao()

        if self.cartao_detectado and self.drive_path:
            self.atualizar_ui_cartao_detectado(self.drive_path, e_manual=self.origem_manual)
        else:
            self.atualizar_ui_cartao_removido()

    def ao_selecionar_fotografo(self, opcao):
        if opcao == "Outro...":
            self.entry_nome_outro.pack(pady=(2, 4), padx=30, fill="x")
        else:
            self.entry_nome_outro.pack_forget()
        self.atualizar_caminho_final_exibicao()

    def obter_nome_fotografo_ativo(self):
        if self.active_servir:
            if hasattr(self, 'combo_fotografo_var'):
                escolha = self.combo_fotografo_var.get()
                if escolha == "Outro...":
                    if hasattr(self, 'entry_nome_outro') and self.entry_nome_outro.winfo_exists():
                        return self.entry_nome_outro.get().strip()
                    return ""
                return escolha
            return ""
        else:
            if hasattr(self, 'entry_nome') and self.entry_nome.winfo_exists():
                return self.entry_nome.get().strip()
            return ""

    def calcular_caminho_final(self, base_destino, nome_fotografo):
        if not base_destino or not nome_fotografo:
            return base_destino
            
        if self.active_servir:
            nome_servir = self.active_servir.get('nome')
            base_servir = os.path.join(base_destino, nome_servir)
            categoria = self.combo_categoria_var.get()
            if categoria == "Raiz (Nenhuma)":
                destino = os.path.join(base_servir, nome_fotografo)
            else:
                destino = os.path.join(base_servir, categoria, nome_fotografo)
        else:
            if self.criar_pasta_fotografo_var.get():
                destino = os.path.join(base_destino, nome_fotografo)
            else:
                destino = base_destino
                
        # Lógica de segunda/consecutiva ingestão
        tem_pasta_fotografo = False
        if self.active_servir:
            tem_pasta_fotografo = True
        else:
            if self.criar_pasta_fotografo_var.get():
                tem_pasta_fotografo = True
                
        if tem_pasta_fotografo and nome_fotografo != "(Aguardando nome do fotógrafo)":
            ja_descarregou = False
            if os.path.exists(destino):
                for root, dirs, files in os.walk(destino):
                    for f in files:
                        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.cr2', '.nef', '.arw', '.cr3', '.mp4')):
                            ja_descarregou = True
                            break
                    if ja_descarregou:
                        break
            
            if ja_descarregou:
                subfolder_num = 2
                while os.path.exists(os.path.join(destino, f"{nome_fotografo}_{subfolder_num}")):
                    subfolder_num += 1
                destino = os.path.join(destino, f"{nome_fotografo}_{subfolder_num}")
                
        return destino

    def atualizar_caminho_final_exibicao(self, *args):
        try:
            base_destino = self.destino_path.get()
            if not base_destino:
                final_path = "Selecione a pasta de destino acima..."
            else:
                nome_fotografo = self.obter_nome_fotografo_ativo()
                if not nome_fotografo:
                    nome_fotografo = "(Aguardando nome do fotógrafo)"
                final_path = self.calcular_caminho_final(base_destino, nome_fotografo)
                
            if hasattr(self, 'entry_caminho_final') and self.entry_caminho_final.winfo_exists():
                self.entry_caminho_final.configure(state="normal")
                self.entry_caminho_final.delete(0, 'end')
                self.entry_caminho_final.insert(0, final_path)
                self.entry_caminho_final.configure(state="readonly")
        except Exception as e:
            print(f"Erro ao atualizar caminho final: {e}")

    def iniciar_traces(self):
        # Remove traces antigos se existirem para evitar duplicados
        if hasattr(self, '_trace_ids'):
            for var, trace_id in self._trace_ids:
                try:
                    var.trace_remove("write", trace_id)
                except Exception:
                    pass
        self._trace_ids = []
        
        # Registra novos traces de forma reativa
        try:
            tid = self.destino_path.trace_add("write", self.atualizar_caminho_final_exibicao)
            self._trace_ids.append((self.destino_path, tid))
            
            if self.active_servir:
                tid1 = self.combo_fotografo_var.trace_add("write", self.atualizar_caminho_final_exibicao)
                self._trace_ids.append((self.combo_fotografo_var, tid1))
                
                tid3 = self.combo_categoria_var.trace_add("write", self.atualizar_caminho_final_exibicao)
                self._trace_ids.append((self.combo_categoria_var, tid3))
            else:
                tid2 = self.criar_pasta_fotografo_var.trace_add("write", self.atualizar_caminho_final_exibicao)
                self._trace_ids.append((self.criar_pasta_fotografo_var, tid2))
        except Exception as e:
            print(f"Erro ao registrar traces: {e}")

    def registrar_historico(self, total_selecionadas=None):
        try:
            caminho_hist = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historico_downloads.json")
            historico = []
            if os.path.exists(caminho_hist):
                try:
                    with open(caminho_hist, 'r', encoding='utf-8') as f:
                        historico = json.load(f)
                except Exception:
                    pass
            
            nome_fotografo = self.obter_nome_fotografo_ativo()
            
            # Se for uma atualização de revisão
            if total_selecionadas is not None and historico:
                # Procura a última entrada deste fotógrafo e destino para atualizar
                for entry in reversed(historico):
                    if entry.get("fotografo") == self.sessao_fotografo and entry.get("destino") == self.sessao_destino:
                        entry["selecionadas"] = total_selecionadas
                        break
            else:
                # Nova entrada de descarregamento
                destino = self.destino_path.get()
                
                if self.active_servir:
                    nome_servir = self.active_servir.get('nome')
                    categoria = self.combo_categoria_var.get()
                    if categoria == "Raiz (Nenhuma)":
                        destino = os.path.join(destino, nome_servir, nome_fotografo)
                    else:
                        destino = os.path.join(destino, nome_servir, categoria, nome_fotografo)
                else:
                    if self.criar_pasta_fotografo_var.get():
                        destino = os.path.join(destino, nome_fotografo)
                
                # Armazena na sessão
                self.sessao_fotografo = nome_fotografo
                self.sessao_destino = destino
                
                total_descarregadas = len(self.arquivos_transferidos)
                
                hoje = date.today().isoformat()
                hora = time.strftime("%H:%M:%S")
                
                nova_entrada = {
                    "data": hoje,
                    "hora": hora,
                    "fotografo": nome_fotografo,
                    "descarregadas": total_descarregadas,
                    "selecionadas": total_descarregadas, # Inicialmente todas
                    "destino": destino
                }
                historico.append(nova_entrada)
                
            with open(caminho_hist, 'w', encoding='utf-8') as f:
                json.dump(historico, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Erro ao registrar histórico: {e}")

    def recarregar_combo_drive(self):
        self.pastas_drive = self.carregar_config_pastas()
        valores_menu = []
        
        # Adiciona pastas do Drive do Servir ativo
        if self.active_servir:
            drive_folders = self.active_servir.get('drive_folders', [])
            if not drive_folders and self.active_servir.get('drive_link'):
                drive_folders = [{"link": self.active_servir.get('drive_link'), "nome": self.active_servir.get('drive_nome', 'Configurada')}]
                
            for folder in drive_folders:
                valores_menu.append(f"Pasta do Servir: {folder.get('nome')}")
                
        valores_menu.append("Raiz do Google Drive (Padrão)")
        for p in self.pastas_drive:
            valores_menu.append(p['nome'])
            
        if hasattr(self, 'combo_drive'):
            self.combo_drive.configure(values=valores_menu)
            
        opcao_atual = self.combo_drive_var.get()
        if opcao_atual not in valores_menu:
            if valores_menu:
                self.combo_drive_var.set(valores_menu[0])
            else:
                self.combo_drive_var.set("Raiz do Google Drive (Padrão)")

    def obter_link_drive_selecionado(self):
        opcao_selecionada = self.combo_drive_var.get()
        if self.active_servir:
            drive_folders = self.active_servir.get('drive_folders', [])
            if not drive_folders and self.active_servir.get('drive_link'):
                drive_folders = [{"link": self.active_servir.get('drive_link'), "nome": self.active_servir.get('drive_nome', 'Configurada')}]
                
            for folder in drive_folders:
                if opcao_selecionada == f"Pasta do Servir: {folder.get('nome')}":
                    return folder.get('link')
                    
        if opcao_selecionada == "Raiz do Google Drive (Padrão)":
            return ""
        for p in self.pastas_drive:
            if p['nome'] == opcao_selecionada:
                return p['link']
        return ""

    def recarregar_combo_destino(self):
        self.pastas_local = self.carregar_config_pastas_local()
        
        # Padrão é a pasta padrão do aplicativo, ou a pasta do Servir se tiver uma ativa!
        default_destination = self.destino_padrao_app
        if self.active_servir and self.active_servir.get('local_path'):
            if os.path.exists(self.active_servir.get('local_path')):
                default_destination = self.active_servir.get('local_path')
                
        self.destino_path.set(default_destination)
        if not hasattr(self, 'combo_destino') or not self.combo_destino.winfo_exists():
            return
            
        valores_menu = []
        if self.active_servir and self.active_servir.get('local_path'):
            local_nome = self.active_servir.get('local_nome') or os.path.basename(self.active_servir.get('local_path')) or "Pasta do Servir"
            valores_menu.append(f"Pasta do Servir: {local_nome}")
            
        valores_menu.append("Pasta do Aplicativo (Padrão)")
        for p in self.pastas_local:
            valores_menu.append(p['nome'])
        valores_menu.append("Escolher pasta personalizada...")
        self.combo_destino.configure(values=valores_menu)
        
        opcao_atual = self.combo_destino_var.get()
        if opcao_atual not in valores_menu:
            if self.active_servir and self.active_servir.get('local_path'):
                local_nome = self.active_servir.get('local_nome') or os.path.basename(self.active_servir.get('local_path')) or "Pasta do Servir"
                self.combo_destino_var.set(f"Pasta do Servir: {local_nome}")
                self.destino_path.set(self.active_servir.get('local_path'))
            else:
                self.combo_destino_var.set("Pasta do Aplicativo (Padrão)")
                self.destino_path.set(self.destino_padrao_app)
        else:
            if self.active_servir and opcao_atual.startswith("Pasta do Servir:"):
                self.destino_path.set(self.active_servir.get('local_path'))
            elif opcao_atual == "Pasta do Aplicativo (Padrão)":
                self.destino_path.set(self.destino_padrao_app)
            elif opcao_atual != "Escolher pasta personalizada...":
                for p in self.pastas_local:
                    if p['nome'] == opcao_atual:
                        self.destino_path.set(p['caminho'])
                        break

    def ao_alterar_destino_combo(self, opcao):
        if opcao == "Escolher pasta personalizada...":
            self.selecionar_destino()
        elif opcao == "Pasta do Aplicativo (Padrão)":
            self.destino_path.set(self.destino_padrao_app)
        elif self.active_servir and opcao.startswith("Pasta do Servir:"):
            self.destino_path.set(self.active_servir.get('local_path'))
        else:
            for p in self.pastas_local:
                if p['nome'] == opcao:
                    self.destino_path.set(p['caminho'])
                    break
        self.atualizar_caminho_final_exibicao()

    def monitorar_cartao(self):
        drives_iniciais = {p.device: p.mountpoint for p in psutil.disk_partitions() if p.mountpoint}
        while True:
            time.sleep(1.5)
            drives_atuais = {p.device: p.mountpoint for p in psutil.disk_partitions() if p.mountpoint}
            novos_devices = [d for d in drives_atuais if d not in drives_iniciais]
            
            if novos_devices:
                device_novo = novos_devices[0]
                mountpoint_novo = drives_atuais[device_novo]
                
                self.drive_path = mountpoint_novo
                self.cartao_detectado = True
                self.origem_manual = False
                
                self.after(0, lambda path=self.drive_path: self.atualizar_ui_cartao_detectado(path))
                self.abrir_pasta_dcim(self.drive_path)
                drives_iniciais = drives_atuais
            elif len(drives_atuais) < len(drives_iniciais):
                if self.origem_manual:
                    drives_iniciais = drives_atuais
                else:
                    self.drive_path = ""
                    self.cartao_detectado = False
                    self.after(0, self.atualizar_ui_cartao_removido)
                    drives_iniciais = drives_atuais

    def abrir_pasta_dcim(self, drive):
        caminho_dcim = os.path.join(drive, "DCIM")
        alvo = caminho_dcim if os.path.exists(caminho_dcim) and os.path.isdir(caminho_dcim) else drive
        if os.path.exists(alvo) and os.path.isdir(alvo):
            try:
                if platform.system() == "Windows":
                    os.startfile(alvo)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", alvo])
                else:
                    subprocess.Popen(["xdg-open", alvo])
            except Exception as e:
                print(f"Erro ao abrir pasta {alvo}: {e}")

    def selecionar_origem_manual(self):
        pasta = filedialog.askdirectory(title="Selecione a pasta de origem das fotos (Cartão ou Pasta)")
        if pasta:
            self.drive_path = pasta
            self.cartao_detectado = True
            self.origem_manual = True
            self.atualizar_ui_cartao_detectado(pasta, e_manual=True)

    def atualizar_ui_cartao_detectado(self, drive, e_manual=False):
        if e_manual:
            self.lbl_status.configure(text=f"Origem Manual Selecionada: {drive}", text_color="#3498db")
        else:
            self.lbl_status.configure(text=f"Cartão Detectado: {drive}", text_color="lightgreen")
            
        for widget in self.frame_pastas.winfo_children():
            widget.destroy()
        self.checkboxes_pastas.clear()
        
        try:
            pastas_encontradas = []
            
            var_raiz = ctk.StringVar(value="")
            cb_raiz = ctk.CTkCheckBox(
                self.frame_pastas, 
                text="[Pasta Completa] Importar tudo desta pasta principal", 
                variable=var_raiz, 
                onvalue=".", 
                offvalue="",
                text_color="#3498db" if e_manual else "#2ecc71"
            )
            cb_raiz.pack(anchor="w", pady=5, padx=10)
            self.checkboxes_pastas.append(var_raiz)
            
            caminho_dcim = os.path.join(drive, "DCIM")
            
            if os.path.exists(caminho_dcim) and os.path.isdir(caminho_dcim):
                for sub_item in os.listdir(caminho_dcim):
                    caminho_sub = os.path.join(caminho_dcim, sub_item)
                    if os.path.isdir(caminho_sub):
                        pastas_encontradas.append(f"DCIM/{sub_item}")
            else:
                for item in os.listdir(drive):
                    caminho_completo = os.path.join(drive, item)
                    if os.path.isdir(caminho_completo) and not item.startswith('$'):
                        pastas_encontradas.append(item)

            for pasta in pastas_encontradas:
                var = ctk.StringVar(value="")
                cb = ctk.CTkCheckBox(self.frame_pastas, text=pasta, variable=var, onvalue=pasta, offvalue="")
                cb.pack(anchor="w", pady=5, padx=10)
                self.checkboxes_pastas.append(var)
                
        except Exception as e:
            print(f"Erro ao ler cartão: {e}")

    def atualizar_ui_cartao_removido(self):
        self.lbl_status.configure(text="Aguardando inserção do Cartão SD...", text_color="orange")
        for widget in self.frame_pastas.winfo_children():
            widget.destroy()
        self.checkboxes_pastas.clear()
        self.lbl_vazio = ctk.CTkLabel(self.frame_pastas, text="Nenhum cartão detectado.")
        self.lbl_vazio.pack(pady=15)

    def selecionar_destino(self):
        pasta = filedialog.askdirectory(title="Selecione onde salvar as fotos")
        if pasta:
            self.destino_path.set(pasta)
            if hasattr(self, 'combo_destino_var'):
                self.combo_destino_var.set("Escolher pasta personalizada...")
        else:
            if not self.destino_path.get() or self.destino_path.get() == self.destino_padrao_app:
                if hasattr(self, 'combo_destino_var'):
                    self.combo_destino_var.set("Pasta do Aplicativo (Padrão)")
                self.destino_path.set(self.destino_padrao_app)
            else:
                encontrou = False
                for p in self.pastas_local:
                    if p['caminho'] == self.destino_path.get():
                        if hasattr(self, 'combo_destino_var'):
                            self.combo_destino_var.set(p['nome'])
                        encontrou = True
                        break
                if not encontrou:
                    if hasattr(self, 'combo_destino_var'):
                        self.combo_destino_var.set("Escolher pasta personalizada...")
        self.atualizar_caminho_final_exibicao()

    def novo_descarregamento(self):
        if hasattr(self, 'combo_fotografo_var'):
            if self.active_servir and self.active_servir.get('voluntarios'):
                self.combo_fotografo_var.set(self.active_servir['voluntarios'][0])
            if hasattr(self, 'entry_nome_outro'):
                self.entry_nome_outro.delete(0, 'end')
                self.entry_nome_outro.pack_forget()
        if hasattr(self, 'entry_nome'):
            self.entry_nome.delete(0, 'end')
            
        self.arquivos_transferidos.clear()
        
        self.progressbar.set(0)
        self.lbl_progresso.configure(text="Progresso: 0%")
        
        self.btn_selecionar.configure(state="disabled")
        self.btn_abrir.configure(state="disabled")
        self.btn_enviar_drive.configure(state="disabled")
        self.btn_iniciar.configure(state="normal")
        
        self.recarregar_combo_drive()
        self.recarregar_combo_destino()
        
        if self.cartao_detectado and self.drive_path:
            self.atualizar_ui_cartao_detectado(self.drive_path, e_manual=self.origem_manual)
        else:
            self.atualizar_ui_cartao_removido()
            
        self.atualizar_caminho_final_exibicao()

    def iniciar_transferencia(self):
        if not self.cartao_detectado:
            messagebox.showwarning("Aviso", "Nenhum cartão SD detectado!")
            return
            
        nome_fotografo = self.obter_nome_fotografo_ativo()
        if not nome_fotografo:
            messagebox.showwarning("Aviso", "Por favor, selecione ou digite o nome do fotógrafo!")
            return
            
        destino = self.destino_path.get()
        if not destino:
            messagebox.showwarning("Aviso", "Selecione a pasta de destino no computador!")
            return

        pastas_selecionadas = [var.get() for var in self.checkboxes_pastas if var.get() != ""]
        if not pastas_selecionadas:
            messagebox.showwarning("Aviso", "Selecione pelo menos uma pasta do cartão para descarregar!")
            return

        self.btn_iniciar.configure(state="disabled")
        self.btn_selecionar.configure(state="disabled")
        self.btn_abrir.configure(state="disabled")
        if hasattr(self, 'combo_destino') and self.combo_destino.winfo_exists():
            self.combo_destino.configure(state="disabled")
        if hasattr(self, 'combo_fotografo'):
            self.combo_fotografo.configure(state="disabled")
        if hasattr(self, 'entry_nome_outro'):
            self.entry_nome_outro.configure(state="disabled")
        if hasattr(self, 'combo_categoria'):
            self.combo_categoria.configure(state="disabled")
        
        self.arquivos_transferidos.clear()
        
        thread_copia = threading.Thread(
            target=self.processar_copia, 
            args=(nome_fotografo, destino, pastas_selecionadas)
        )
        thread_copia.start()

    def processar_copia(self, nome_fotografo, destino, pastas_selecionadas):


        # Calcula o caminho final completo da pasta onde as fotos serão salvas usando o helper
        destino = self.calcular_caminho_final(destino, nome_fotografo)
        
        # Identifica a pasta principal do fotógrafo (destino_base_fotografo)
        destino_base_fotografo = destino
        nome_dir = os.path.basename(destino)
        if nome_dir.startswith(f"{nome_fotografo}_"):
            parte_sufixo = nome_dir[len(nome_fotografo)+1:]
            if parte_sufixo.isdigit():
                destino_base_fotografo = os.path.dirname(destino)
                
        os.makedirs(destino, exist_ok=True)
        arquivos_para_copiar = []
        ja_descarregados = 0
        total_encontrados = 0
        
        for pasta_relativa in pastas_selecionadas:
            pasta_origem = os.path.join(self.drive_path, os.path.normpath(pasta_relativa))
            if os.path.exists(pasta_origem):
                arquivos_por_diretorio = {}
                for root, dirs, files in os.walk(pasta_origem):
                    for file in files:
                        if file.lower().endswith(('.png', '.jpg', '.jpeg', '.cr2', '.nef', '.arw', '.cr3', '.mp4')):
                            if file != "FOTOS_DESCARREGADAS_ATE_AQUI.txt":
                                arquivos_por_diretorio.setdefault(root, []).append(file)
                                
                for subdir, files in arquivos_por_diretorio.items():
                    total_encontrados += len(files)
                    try:
                        files.sort(key=lambda f: os.path.getmtime(os.path.join(subdir, f)))
                    except Exception:
                        files.sort()
                        
                    marker_path = os.path.join(subdir, "FOTOS_DESCARREGADAS_ATE_AQUI.txt")
                    if os.path.exists(marker_path):
                        last_file_name = None
                        last_file_mtime = None
                        try:
                            with open(marker_path, 'r', encoding='utf-8') as f:
                                for line in f:
                                    if line.startswith("Último arquivo importado:"):
                                        last_file_name = line.split(":", 1)[1].strip()
                                    elif line.startswith("Timestamp do último arquivo:"):
                                        last_file_mtime = float(line.split(":", 1)[1].strip())
                        except Exception as e:
                            print(f"Erro ao ler marker file em {subdir}: {e}")
                            
                        if last_file_mtime is None:
                            try:
                                last_file_mtime = os.path.getmtime(marker_path)
                            except Exception:
                                pass
                                
                        filtered_files = []
                        if last_file_name and last_file_name in files:
                            idx = files.index(last_file_name)
                            ja_descarregados += (idx + 1)
                            for f in files[idx+1:]:
                                filtered_files.append(os.path.join(subdir, f))
                        else:
                            for f in files:
                                f_path = os.path.join(subdir, f)
                                try:
                                    f_mtime = os.path.getmtime(f_path)
                                except Exception:
                                    f_mtime = 0
                                if last_file_mtime is not None and f_mtime > last_file_mtime:
                                    filtered_files.append(f_path)
                                elif last_file_mtime is None:
                                    filtered_files.append(f_path)
                                else:
                                    ja_descarregados += 1
                        arquivos_para_copiar.extend(filtered_files)
                    else:
                        for f in files:
                            arquivos_para_copiar.append(os.path.join(subdir, f))
                            
        if total_encontrados == 0:
            self.after(0, lambda: messagebox.showinfo("Informação", "Nenhuma imagem encontrada nas pastas selecionadas."))
            self.after(0, lambda: self.btn_iniciar.configure(state="normal"))
            return
            
        if len(arquivos_para_copiar) == 0 and ja_descarregados > 0:
            confirmar_reimport = [False]
            event_reimport = threading.Event()
            
            def exibir_confirmacao_reimport():
                res = messagebox.askyesno(
                    "Fotos Já Descarregadas",
                    f"Atenção: Todas as {ja_descarregados} fotos encontradas já foram descarregadas anteriormente!\n\n"
                    "Deseja descarregá-las novamente?"
                )
                confirmar_reimport[0] = res
                event_reimport.set()
                
            self.after(0, exibir_confirmacao_reimport)
            event_reimport.wait()
            
            if confirmar_reimport[0]:
                for pasta_relativa in pastas_selecionadas:
                    pasta_origem = os.path.join(self.drive_path, os.path.normpath(pasta_relativa))
                    if os.path.exists(pasta_origem):
                        for root, dirs, files in os.walk(pasta_origem):
                            for file in files:
                                if file.lower().endswith(('.png', '.jpg', '.jpeg', '.cr2', '.nef', '.arw', '.cr3', '.mp4')):
                                    if file != "FOTOS_DESCARREGADAS_ATE_AQUI.txt":
                                        arquivos_para_copiar.append(os.path.join(root, file))
            else:
                def reativar_controles():
                    self.btn_iniciar.configure(state="normal")
                    if hasattr(self, 'combo_destino') and self.combo_destino.winfo_exists():
                        self.combo_destino.configure(state="normal")
                    if hasattr(self, 'combo_fotografo'):
                        self.combo_fotografo.configure(state="normal")
                    if hasattr(self, 'entry_nome_outro'):
                        self.entry_nome_outro.configure(state="normal")
                    if hasattr(self, 'combo_categoria'):
                        self.combo_categoria.configure(state="normal")
                self.after(0, reativar_controles)
                return
                
        elif len(arquivos_para_copiar) > 0 and ja_descarregados > 0:
            confirmar_novas = [True]
            event_novas = threading.Event()
            
            def exibir_confirmacao_novas():
                res = messagebox.askyesno(
                    "Fotos Já Descarregadas",
                    f"Atenção: Foram detectadas {ja_descarregados} fotos já descarregadas anteriormente nesta pasta.\n\n"
                    f"Deseja descarregar apenas as {len(arquivos_para_copiar)} novas fotos tiradas após o último descarregamento?\n"
                    f"(Se selecionar 'Não', todas as {len(arquivos_para_copiar) + ja_descarregados} fotos serão copiadas)."
                )
                confirmar_novas[0] = res
                event_novas.set()
                
            self.after(0, exibir_confirmacao_novas)
            event_novas.wait()
            
            if not confirmar_novas[0]:
                arquivos_para_copiar = []
                for pasta_relativa in pastas_selecionadas:
                    pasta_origem = os.path.join(self.drive_path, os.path.normpath(pasta_relativa))
                    if os.path.exists(pasta_origem):
                        for root, dirs, files in os.walk(pasta_origem):
                            for file in files:
                                if file.lower().endswith(('.png', '.jpg', '.jpeg', '.cr2', '.nef', '.arw', '.cr3', '.mp4')):
                                    if file != "FOTOS_DESCARREGADAS_ATE_AQUI.txt":
                                        arquivos_para_copiar.append(os.path.join(root, file))

        total_arquivos = len(arquivos_para_copiar)
        if total_arquivos == 0:
            self.after(0, lambda: messagebox.showinfo("Informação", "Nenhuma imagem encontrada nas pastas selecionadas."))
            self.after(0, lambda: self.btn_iniciar.configure(state="normal"))
            return

        tem_raw = any(f.lower().endswith(('.cr2', '.nef', '.arw', '.cr3')) for f in arquivos_para_copiar)
        if tem_raw:
            confirmar = [True]
            event = threading.Event()
            
            def exibir_aviso():
                res = messagebox.askyesno(
                    "Fotos em RAW Detectadas",
                    "Atenção: Foram detectadas fotos em formato RAW (.cr3, .cr2, .nef, .arw) nas pastas selecionadas.\n\n"
                    "Elas serão copiadas no formato original. Deseja prosseguir com o descarregamento?"
                )
                confirmar[0] = res
                event.set()
                
            self.after(0, exibir_aviso)
            event.wait()
            
            if not confirmar[0]:
                def reativar_controles():
                    self.btn_iniciar.configure(state="normal")
                    if hasattr(self, 'combo_destino') and self.combo_destino.winfo_exists():
                        self.combo_destino.configure(state="normal")
                    if hasattr(self, 'combo_fotografo'):
                        self.combo_fotografo.configure(state="normal")
                    if hasattr(self, 'entry_nome_outro'):
                        self.entry_nome_outro.configure(state="normal")
                    if hasattr(self, 'combo_categoria'):
                        self.combo_categoria.configure(state="normal")
                    if self.arquivos_transferidos:
                        self.btn_selecionar.configure(state="normal")
                        self.btn_abrir.configure(state="normal")
                self.after(0, reativar_controles)
                return

        try:
            arquivos_para_copiar.sort(key=lambda x: os.path.getmtime(x))
        except Exception:
            arquivos_para_copiar.sort()

        digitos = max(3, len(str(total_arquivos)))

        contador_inicio = 1
        try:
            prefixo = f"{nome_fotografo}_"
            numeros_existentes = []
            for root, dirs, files in os.walk(destino_base_fotografo):
                for f in files:
                    if f.startswith(prefixo):
                        partes_nome = f[len(prefixo):]
                        nome_sem_ext_dest, _ = os.path.splitext(partes_nome)
                        parte_numerica = nome_sem_ext_dest.split('_')[0]
                        if parte_numerica.isdigit():
                            numeros_existentes.append(int(parte_numerica))
            if numeros_existentes:
                contador_inicio = max(numeros_existentes) + 1
        except Exception as e:
            print(f"Erro ao calcular offset de numeração: {e}")

        progresso_atual = 0
        lock = threading.Lock()
        
        copiados_com_sucesso = []
        lock_copiados = threading.Lock()

        def processar_arquivo(item):
            nonlocal progresso_atual
            idx, caminho_arquivo = item
            nome_original = os.path.basename(caminho_arquivo)
            _, ext = os.path.splitext(nome_original)
            
            ext_final = ext.lower()
            num_formatado = f"{idx + contador_inicio:0{digitos}d}"
            novo_nome = f"{nome_fotografo}_{num_formatado}{ext_final}"
            caminho_destino = os.path.join(destino, novo_nome)

            contador = 1
            while os.path.exists(caminho_destino):
                nome_base, ext_base = os.path.splitext(novo_nome)
                caminho_destino = os.path.join(destino, f"{nome_base}_{contador}{ext_base}")
                contador += 1

            try:    
                shutil.copy2(caminho_arquivo, caminho_destino)
                with lock:
                    if caminho_destino.lower().endswith(('.png', '.jpg', '.jpeg', '.cr2', '.nef', '.arw', '.cr3')):
                        self.arquivos_transferidos.append(caminho_destino)
                with lock_copiados:
                    copiados_com_sucesso.append(caminho_arquivo)
            except Exception as e:
                print(f"Erro ao processar {nome_original}: {e}")
            
            with lock:
                progresso_atual += 1
                progresso = progresso_atual / total_arquivos
                percentual = int(progresso * 100)
                self.progressbar.set(progresso)
                self.lbl_progresso.configure(text=f"Progresso: {percentual}% ({progresso_atual}/{total_arquivos})")

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            executor.map(processar_arquivo, enumerate(arquivos_para_copiar))

        # Cria arquivos de marcador no cartão para os diretórios de origem que foram copiados com sucesso
        if copiados_com_sucesso:
            copiados_por_dir = {}
            for path in copiados_com_sucesso:
                dir_name = os.path.dirname(path)
                copiados_por_dir.setdefault(dir_name, []).append(path)
                
            for subdir, paths in copiados_por_dir.items():
                if not paths:
                    continue
                try:
                    paths.sort(key=lambda x: os.path.getmtime(x))
                except Exception:
                    paths.sort()
                
                ultimo_arquivo_path = paths[-1]
                ultimo_arquivo_nome = os.path.basename(ultimo_arquivo_path)
                try:
                    ultimo_mtime = os.path.getmtime(ultimo_arquivo_path)
                except Exception:
                    ultimo_mtime = time.time()
                
                marker_path = os.path.join(subdir, "FOTOS_DESCARREGADAS_ATE_AQUI.txt")
                try:
                    agora_str = time.strftime("%d/%m/%Y %H:%M:%S")
                    with open(marker_path, 'w', encoding='utf-8') as f_marker:
                        f_marker.write("=====================================================\n")
                        f_marker.write(" FOTOS DESCARREGADAS ATÉ ESTE PONTO\n")
                        f_marker.write("=====================================================\n")
                        f_marker.write("Este arquivo indica que as fotos anteriores a ele\n")
                        f_marker.write("já foram importadas para o computador.\n\n")
                        f_marker.write(f"Último arquivo importado: {ultimo_arquivo_nome}\n")
                        f_marker.write(f"Data do descarregamento: {agora_str}\n")
                        f_marker.write(f"Timestamp do último arquivo: {ultimo_mtime}\n")
                        f_marker.write("=====================================================\n")
                    
                    # Define a data de modificação do arquivo marcador para ser 1 segundo após a última foto copiada
                    os.utime(marker_path, (ultimo_mtime + 1.0, ultimo_mtime + 1.0))
                except Exception as e:
                    print(f"Erro ao criar marker file em {subdir}: {e}")

        self.after(0, self.finalizar_transferencia_gui)

    def finalizar_transferencia_gui(self):
        self.btn_iniciar.configure(state="normal")
        self.btn_abrir.configure(state="normal")
        if hasattr(self, 'combo_destino') and self.combo_destino.winfo_exists():
            self.combo_destino.configure(state="normal")
        if hasattr(self, 'combo_fotografo'):
            self.combo_fotografo.configure(state="normal")
        if hasattr(self, 'entry_nome_outro'):
            self.entry_nome_outro.configure(state="normal")
        if hasattr(self, 'combo_categoria'):
            self.combo_categoria.configure(state="normal")
        self.progressbar.set(0)
        self.lbl_progresso.configure(text="Progresso: 0%")
        
        total_fotos = len(self.arquivos_transferidos)
        if total_fotos > 0:
            self.registrar_historico()
            self.btn_selecionar.configure(state="normal")
            self.btn_enviar_drive.configure(state="disabled")
            
            revisar = messagebox.askyesno(
                "Transferência Finalizada",
                f"Foram transferidas {total_fotos} foto(s) com sucesso!\n\n"
                "Deseja iniciar a tela de seleção agora para revisar e apagar as fotos indesejadas?"
            )
            if revisar:
                self.abrir_revisor()
            else:
                self.btn_enviar_drive.configure(state="normal")
        else:
            self.btn_enviar_drive.configure(state="disabled")
            messagebox.showinfo("Concluído", "A cópia foi finalizada, mas nenhuma imagem compatível com revisão foi transferida.")

    def abrir_revisor(self):
        if not self.arquivos_transferidos:
            messagebox.showwarning("Aviso", "Não há fotos na lista de transferência para revisar.")
            return
            
        self.btn_selecionar.configure(state="disabled")
        self.btn_abrir.configure(state="disabled")
        self.btn_enviar_drive.configure(state="disabled")
        
        if self.active_servir:
            base_destino = self.destino_path.get()
            nome_servir = self.active_servir.get('nome')
            nome_fotografo = self.obter_nome_fotografo_ativo()
            categoria = self.combo_categoria_var.get()
            if categoria == "Raiz (Nenhuma)":
                destino_final = os.path.join(base_destino, nome_servir, nome_fotografo)
            else:
                destino_final = os.path.join(base_destino, nome_servir, categoria, nome_fotografo)
        else:
            destino_final = self.destino_path.get()
            if self.criar_pasta_fotografo_var.get():
                destino_final = os.path.join(destino_final, self.obter_nome_fotografo_ativo())
                
        self.janela_revisao = RevisorFotosWindow(self, self.arquivos_transferidos, destino_final)

    def abrir_pasta(self):
        destino = self.destino_path.get()
        nome_fotografo = self.obter_nome_fotografo_ativo()
        
        if self.active_servir:
            nome_servir = self.active_servir.get('nome')
            categoria = self.combo_categoria_var.get()
            if categoria == "Raiz (Nenhuma)":
                destino_final = os.path.join(destino, nome_servir, nome_fotografo)
            else:
                destino_final = os.path.join(destino, nome_servir, categoria, nome_fotografo)
            if os.path.exists(destino_final):
                destino = destino_final
            elif os.path.exists(os.path.join(destino, nome_servir, categoria)):
                destino = os.path.join(destino, nome_servir, categoria)
            elif os.path.exists(os.path.join(destino, nome_servir)):
                destino = os.path.join(destino, nome_servir)
        else:
            if nome_fotografo and self.criar_pasta_fotografo_var.get():
                destino_sub = os.path.join(destino, nome_fotografo)
                if os.path.exists(destino_sub):
                    destino = destino_sub
                    
        if destino and os.path.exists(destino):
            try:
                if platform.system() == "Windows":
                    os.startfile(destino)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", destino])
                else:
                    subprocess.Popen(["xdg-open", destino])
            except Exception as e:
                print(f"Erro ao abrir pasta: {e}")

    def abrir_pasta_raiz_servir(self):
        if not self.active_servir:
            return
        destino_base = self.destino_path.get()
        if not destino_base:
            return
        nome_servir = self.active_servir.get('nome')
        pasta_raiz = os.path.join(destino_base, nome_servir)
        if os.path.exists(pasta_raiz):
            try:
                if platform.system() == "Windows":
                    os.startfile(pasta_raiz)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", pasta_raiz])
                else:
                    subprocess.Popen(["xdg-open", pasta_raiz])
            except Exception as e:
                print(f"Erro ao abrir pasta raiz: {e}")
        else:
            messagebox.showinfo("Informação", f"A pasta raiz do servir '{nome_servir}' ainda não foi criada localmente.")

    def finalizar_servir_thread(self):
        if not self.active_servir:
            messagebox.showwarning("Aviso", "Nenhum dia de Servir ativo para finalizar.")
            return
            
        confirmar = messagebox.askyesno(
            "Finalizar Servir", 
            "Tem certeza que deseja finalizar este Servir e enviar todos os dados para o webhook?"
        )
        if not confirmar:
            return
            
        # Desabilita o botão para evitar múltiplos cliques
        if hasattr(self, 'btn_finalizar_servir') and self.btn_finalizar_servir.winfo_exists():
            self.btn_finalizar_servir.configure(state="disabled", text="Enviando...")
            
        # Inicia a thread
        threading.Thread(target=self.executar_finalizar_servir, daemon=True).start()

    def executar_finalizar_servir(self):
        try:
            import requests
            nome_servir = self.active_servir.get('nome')
            destino_base = self.destino_path.get()
            
            # 1. Monta o payload inicial do Servir
            payload = {
                "servir": {
                    "id": self.active_servir.get("id"),
                    "nome": nome_servir,
                    "data_criacao": self.active_servir.get("data_criacao"),
                    "drive_link": self.active_servir.get("drive_link"),
                    "drive_nome": self.active_servir.get("drive_nome"),
                    "voluntarios": self.active_servir.get("voluntarios", []),
                    "pastas_predefinidas": self.active_servir.get("pastas_predefinidas", [])
                },
                "categorias": []
            }
            
            # 2. Obter estatísticas locais
            local_stats = self.obter_estatisticas_locais()
            
            # 3. Obter estatísticas das estações auxiliares conectadas
            aux_stats_list = []
            estacoes_com_erro = []
            
            if self.network_mode == "lider" and self.auxiliar_stations:
                for ip, info in list(self.auxiliar_stations.items()):
                    try:
                        url = f"http://{ip}:{info['port']}/stats"
                        res = requests.get(url, timeout=3.0)
                        if res.status_code == 200:
                            dados = res.json()
                            aux_stats_list.append(dados.get("categorias", []))
                        else:
                            estacoes_com_erro.append(info['nome'])
                    except Exception:
                        estacoes_com_erro.append(info['nome'])
                        
            # Se houver erro de conexão com algum auxiliar, pergunta se deseja prosseguir
            if estacoes_com_erro:
                confirmar_aviso = []
                evt = threading.Event()
                def exibir_confirmacao():
                    res = messagebox.askyesno(
                        "Erro de Comunicação LAN",
                        f"Não foi possível obter dados das seguintes estações:\n"
                        f"{', '.join(estacoes_com_erro)}\n\n"
                        "Deseja finalizar o Servir mesmo assim (ignorando estas estações)?"
                    )
                    confirmar_aviso.append(res)
                    evt.set()
                self.after(0, exibir_confirmacao)
                evt.wait()
                if not confirmar_aviso or not confirmar_aviso[0]:
                    # Cancela a finalização
                    self.after(0, lambda: self.btn_finalizar_servir.configure(state="normal", text="🏁 Finalizar Servir"))
                    return
            
            # Mesclar as estatísticas
            categorias_final = mesclar_estatisticas(local_stats, aux_stats_list)
            payload["categorias"] = categorias_final
            
            # 4. Envia o payload via POST para o webhook
            url_webhook = "https://sistema-crescer-n8n.vuvd0x.easypanel.host/webhook/finalizar-servir"
            headers = {"Content-Type": "application/json"}
            
            resposta = requests.post(url_webhook, json=payload, headers=headers, timeout=30)
            
            # 5. Trata a resposta
            if resposta.status_code in [200, 201]:
                # Notifica todas as estações auxiliares para finalizarem remotamente
                if self.network_mode == "lider" and self.auxiliar_stations:
                    for ip, info in list(self.auxiliar_stations.items()):
                        try:
                            url = f"http://{ip}:{info['port']}/finalize"
                            requests.post(url, timeout=2.0)
                        except Exception:
                            pass
                self.after(0, lambda: self.finalizar_servir_sucesso())
            else:
                self.after(0, lambda r=resposta: self.finalizar_servir_erro(f"Código de status: {r.status_code}"))
                
        except Exception as e:
            self.after(0, lambda err=e: self.finalizar_servir_erro(str(err)))

    def finalizar_servir_sucesso(self):
        if hasattr(self, 'btn_finalizar_servir') and self.btn_finalizar_servir.winfo_exists():
            self.btn_finalizar_servir.configure(state="normal", text="🏁 Finalizar Servir")
        messagebox.showinfo("Sucesso", "Servir finalizado com sucesso! Todos os dados foram enviados para o webhook.")
        self.active_servir = None
        self.mostrar_pagina_inicial()
        
    def finalizar_servir_erro(self, erro_msg):
        if hasattr(self, 'btn_finalizar_servir') and self.btn_finalizar_servir.winfo_exists():
            self.btn_finalizar_servir.configure(state="normal", text="🏁 Finalizar Servir")
        messagebox.showerror("Erro ao Finalizar", f"Não foi possível enviar os dados ao webhook:\n{erro_msg}")

    def extrair_id_pasta_drive(self, link_ou_id):
        link_ou_id = link_ou_id.strip()
        if not link_ou_id:
            return 'root'
        if "drive.google.com" in link_ou_id:
            partes = link_ou_id.split("/folders/")
            if len(partes) > 1:
                subparte = partes[1].split("?")[0].split("/")[0]
                return subparte
        return link_ou_id

    def iniciar_upload_drive(self):
        if not GOOGLE_DRIVE_DISPONIVEL:
            messagebox.showerror(
                "Bibliotecas Faltando", 
                "As bibliotecas da API do Google Drive não estão disponíveis.\n\n"
                "Por favor, execute: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
            )
            return

        if not self.arquivos_transferidos:
            messagebox.showwarning("Aviso", "Não há fotos disponíveis para upload!")
            return

        caminho_credenciais = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")
        if not os.path.exists(caminho_credenciais):
            messagebox.showerror(
                "Credenciais Não Encontradas", 
                "O arquivo 'credentials.json' não foi encontrado na pasta do aplicativo!\n\n"
                "Por favor, salve o arquivo como 'credentials.json' na pasta do programa."
            )
            return

        self.btn_iniciar.configure(state="disabled")
        self.btn_selecionar.configure(state="disabled")
        self.btn_abrir.configure(state="disabled")
        self.btn_enviar_drive.configure(state="disabled")
        self.btn_manual.configure(state="disabled")
        self.combo_drive.configure(state="disabled")
        if hasattr(self, 'combo_destino') and self.combo_destino.winfo_exists():
            self.combo_destino.configure(state="disabled")
        if hasattr(self, 'combo_fotografo'):
            self.combo_fotografo.configure(state="disabled")
        if hasattr(self, 'entry_nome_outro'):
            self.entry_nome_outro.configure(state="disabled")
        if hasattr(self, 'combo_categoria'):
            self.combo_categoria.configure(state="disabled")

        link_pasta = self.obter_link_drive_selecionado()

        thread_upload = threading.Thread(
            target=self.processar_upload_drive, 
            args=(caminho_credenciais, link_pasta), 
            daemon=True
        )
        thread_upload.start()

    def processar_upload_drive(self, caminho_credenciais, link_pasta):
        SCOPES = ['https://www.googleapis.com/auth/drive']
        token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'token.json')
        creds = None
        
        if os.path.exists(token_path):
            try:
                creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            except Exception as e:
                print(f"Erro ao carregar token.json: {e}")
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    self.after(0, lambda: self.lbl_progresso.configure(text="Atualizando acesso com o Google..."))
                    creds.refresh(Request())
                except Exception:
                    creds = None
            
            if not creds:
                self.after(0, lambda: messagebox.showinfo(
                    "Autenticação do Google", 
                    "Uma janela do seu navegador será aberta para login com sua conta do Google.\n\n"
                    "Por favor, confirme a autorização."
                ))
                try:
                    self.after(0, lambda: self.lbl_progresso.configure(text="Aguardando autorização no navegador..."))
                    flow = InstalledAppFlow.from_client_secrets_file(caminho_credenciais, SCOPES)
                    creds = flow.run_local_server(port=0)
                    with open(token_path, 'w') as token_file:
                        token_file.write(creds.to_json())
                except Exception as e:
                    self.after(0, lambda: messagebox.showerror("Erro de Autenticação", f"Não foi possível autenticar: {e}"))
                    self.after(0, self.finalizar_upload_gui)
                    return

        try:
            self.after(0, lambda: self.lbl_progresso.configure(text="Conectando ao Google Drive..."))
            service = build('drive', 'v3', credentials=creds)

            folder_id = self.extrair_id_pasta_drive(link_pasta)
            nome_destino_exibicao = "a raiz do seu Google Drive"
            
            if folder_id != 'root':
                self.after(0, lambda: self.lbl_progresso.configure(text="Acessando pasta no Google Drive..."))
                try:
                    pasta_meta = service.files().get(fileId=folder_id, fields='name, mimeType').execute()
                    if pasta_meta.get('mimeType') != 'application/vnd.google-apps.folder':
                        self.after(0, lambda: messagebox.showwarning(
                            "Aviso", 
                            "O link fornecido não pertence a uma pasta do Google Drive. As fotos serão enviadas para a raiz."
                        ))
                        folder_id = 'root'
                    else:
                        nome_destino_exibicao = f"a pasta '{pasta_meta.get('name')}'"
                except Exception as e:
                    self.after(0, lambda: messagebox.showerror(
                        "Pasta Não Encontrada", 
                        "Não foi possível acessar a pasta fornecida no Google Drive.\n\n"
                        "Verifique se o link está correto, se a pasta existe e se possui permissões."
                    ))
                    self.after(0, self.finalizar_upload_gui)
                    return

            # O upload agora envia as fotos diretamente para a pasta selecionada no Drive,
            # sem criar a estrutura de pastas de categorias e fotógrafos.

            arquivos_para_enviar = self.arquivos_transferidos.copy()
            total_arquivos = len(arquivos_para_enviar)
            progresso_atual = 0
            lock_progresso = threading.Lock()

            def enviar_um_arquivo(caminho_arquivo):
                nonlocal progresso_atual
                if not os.path.exists(caminho_arquivo):
                    with lock_progresso:
                        progresso_atual += 1
                        progresso_geral = progresso_atual / total_arquivos
                        self.after(0, lambda pg=progresso_geral: self.progressbar.set(pg))
                    return

                nome_arquivo = os.path.basename(caminho_arquivo)
                service_thread = build('drive', 'v3', credentials=creds)

                file_metadata = {
                    'name': nome_arquivo
                }
                if folder_id != 'root':
                    file_metadata['parents'] = [folder_id]

                ext = os.path.splitext(nome_arquivo)[1].lower()
                if ext in ['.jpg', '.jpeg']:
                    mime = 'image/jpeg'
                elif ext == '.png':
                    mime = 'image/png'
                elif ext in ['.cr2', '.nef', '.arw', '.cr3']:
                    mime = 'image/x-raw'
                elif ext == '.mp4':
                    mime = 'video/mp4'
                else:
                    mime = 'application/octet-stream'

                try:
                    media = MediaFileUpload(caminho_arquivo, mimetype=mime, resumable=True)
                    request = service_thread.files().create(body=file_metadata, media_body=media, fields='id')
                    
                    response = None
                    while response is None:
                        status, response = request.next_chunk()
                except Exception as e:
                    print(f"Erro ao enviar arquivo {nome_arquivo}: {e}")

                with lock_progresso:
                    progresso_atual += 1
                    progresso_geral = progresso_atual / total_arquivos
                    self.after(0, lambda pg=progresso_geral: self.progressbar.set(pg))
                    self.after(0, lambda p=progresso_atual, t=total_arquivos: self.lbl_progresso.configure(
                        text=f"Enviando ({p}/{t}) fotos para o Drive..."
                    ))

            self.after(0, lambda: self.lbl_progresso.configure(text=f"Iniciando envio de {total_arquivos} fotos..."))

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                executor.map(enviar_um_arquivo, arquivos_para_enviar)

            self.after(0, lambda: messagebox.showinfo(
                "Upload Concluído", 
                f"Sucesso! {total_arquivos} fotos foram enviadas com sucesso para {nome_destino_exibicao} no seu Google Drive!"
            ))

        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Erro de Upload", f"Erro durante o envio para o Google Drive: {e}"))

        self.after(0, self.finalizar_upload_gui)

    def finalizar_upload_gui(self):
        self.btn_iniciar.configure(state="normal")
        self.btn_selecionar.configure(state="normal")
        self.btn_abrir.configure(state="normal")
        self.btn_enviar_drive.configure(state="normal")
        self.btn_manual.configure(state="normal")
        self.combo_drive.configure(state="normal")
        if hasattr(self, 'combo_destino') and self.combo_destino.winfo_exists():
            self.combo_destino.configure(state="normal")
        if hasattr(self, 'combo_fotografo'):
            self.combo_fotografo.configure(state="normal")
        if hasattr(self, 'entry_nome_outro'):
            self.entry_nome_outro.configure(state="normal")
        if hasattr(self, 'combo_categoria'):
            self.combo_categoria.configure(state="normal")
        self.progressbar.set(0)
        self.lbl_progresso.configure(text="Progresso: 0%")

if __name__ == "__main__":
    app = ImportadorFotosApp()
    app.mainloop()
