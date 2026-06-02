import customtkinter as ctk
from tkinter import filedialog, messagebox
import os
import shutil
import threading
import time
import psutil
import platform
import subprocess
import rawpy
import imageio
import concurrent.futures
from PIL import Image, ImageOps

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
        self.grab_set()
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
                        if ext in ['.cr2', '.nef', '.arw']:
                            with rawpy.imread(path) as raw:
                                # half_size=True é 4 vezes mais rápido e perfeito para renderizar na tela
                                rgb = raw.postprocess(use_camera_wb=True, half_size=True)
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
            if ext in ['.cr2', '.nef', '.arw']:
                with rawpy.imread(path) as raw:
                    rgb = raw.postprocess(use_camera_wb=True, half_size=True)
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
            
            mensagem = f"Limpeza concluída! {sucessos} foto(s) foram apagadas."
            if erros > 0:
                mensagem += f"\n(Erro ao apagar {erros} foto(s).)"
            messagebox.showinfo("Sucesso", mensagem)
        else:
            messagebox.showinfo("Concluído", "Revisão terminada! Nenhuma foto foi apagada.")
            
        self.limpar_eventos_globais()
        self.grab_release()
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


class ImportadorFotosApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Descarregador de Fotos - Ministério")
        self.geometry("600x780")
        self.resizable(False, False)

        self.destino_path = ctk.StringVar()
        self.cartao_detectado = False
        self.origem_manual = False      # Flag para indicar seleção manual de pasta
        self.drive_path = ""
        self.checkboxes_pastas = []
        self.arquivos_transferidos = [] # Guarda o caminho de todas as fotos transferidas com sucesso
        
        self.setup_ui()
        
        self.monitor_thread = threading.Thread(target=self.monitorar_cartao, daemon=True)
        self.monitor_thread.start()

    def setup_ui(self):
        self.lbl_titulo = ctk.CTkLabel(self, text="Descarregador de Fotos", font=ctk.CTkFont(size=24, weight="bold"))
        self.lbl_titulo.pack(pady=(20, 5))

        self.lbl_status = ctk.CTkLabel(self, text="Aguardando inserção do Cartão SD...", text_color="orange", font=ctk.CTkFont(size=14))
        self.lbl_status.pack(pady=(0, 20))

        self.lbl_nome = ctk.CTkLabel(self, text="Nome do Fotógrafo:")
        self.lbl_nome.pack(anchor="w", padx=40)
        self.entry_nome = ctk.CTkEntry(self, width=520, placeholder_text="Ex: JoaoSilva")
        self.entry_nome.pack(pady=(0, 15), padx=40)

        # Container para a label e o botão de seleção manual
        self.frame_lbl_pastas = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_lbl_pastas.pack(fill="x", padx=40, pady=(0, 5))

        self.lbl_pastas = ctk.CTkLabel(self.frame_lbl_pastas, text="Pastas no Cartão SD:")
        self.lbl_pastas.pack(side="left")

        self.btn_manual = ctk.CTkButton(
            self.frame_lbl_pastas, 
            text="📂 Origem Manual", 
            height=26, 
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#34495e",
            hover_color="#2c3e50",
            command=self.selecionar_origem_manual
        )
        self.btn_manual.pack(side="right")
        
        self.frame_pastas = ctk.CTkScrollableFrame(self, width=500, height=120)
        self.frame_pastas.pack(pady=(0, 15), padx=40)
        
        self.lbl_vazio = ctk.CTkLabel(self.frame_pastas, text="Nenhum cartão detectado.")
        self.lbl_vazio.pack(pady=40)

        self.lbl_destino = ctk.CTkLabel(self, text="Pasta de Destino no Computador:")
        self.lbl_destino.pack(anchor="w", padx=40)
        
        self.frame_destino = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_destino.pack(fill="x", padx=40, pady=(0, 15))
        
        self.entry_destino = ctk.CTkEntry(self.frame_destino, textvariable=self.destino_path, width=400, state="readonly")
        self.entry_destino.pack(side="left", padx=(0, 10))
        
        self.btn_destino = ctk.CTkButton(self.frame_destino, text="Procurar...", width=110, command=self.selecionar_destino)
        self.btn_destino.pack(side="left")

        # Checkbox atualizada para refletir a alta qualidade
        self.converter_raw_var = ctk.BooleanVar(value=False)
        self.chk_converter = ctk.CTkCheckBox(self, text="Converter RAW para JPEG (Processamento Alta Qualidade)", variable=self.converter_raw_var)
        self.chk_converter.pack(anchor="w", padx=40, pady=(0, 15))

        self.lbl_progresso = ctk.CTkLabel(self, text="Progresso: 0%")
        self.lbl_progresso.pack(anchor="w", padx=40)
        self.progressbar = ctk.CTkProgressBar(self, width=520)
        self.progressbar.pack(pady=(5, 20), padx=40)
        self.progressbar.set(0)

        # Botão principal de transferência
        self.frame_botoes = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_botoes.pack(pady=(10, 5), padx=40, fill="x")

        self.btn_iniciar = ctk.CTkButton(
            self.frame_botoes, 
            text="Iniciar Transferência", 
            font=ctk.CTkFont(size=15, weight="bold"), 
            height=45, 
            fg_color="green", 
            hover_color="darkgreen", 
            command=self.iniciar_transferencia
        )
        self.btn_iniciar.pack(fill="x", expand=True)

        # Botões secundários posicionados lado a lado abaixo da transferência
        self.frame_botoes_secundarios = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_botoes_secundarios.pack(pady=(5, 20), padx=40, fill="x")

        self.btn_selecionar = ctk.CTkButton(
            self.frame_botoes_secundarios, 
            text="🔍 Selecionar / Revisar Fotos", 
            height=45, 
            font=ctk.CTkFont(size=14, weight="bold"), 
            fg_color="#1f538d", 
            hover_color="#14375e", 
            command=self.abrir_revisor, 
            state="disabled"
        )
        self.btn_selecionar.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.btn_abrir = ctk.CTkButton(
            self.frame_botoes_secundarios, 
            text="📁 Abrir Pasta", 
            height=45, 
            font=ctk.CTkFont(size=14), 
            command=self.abrir_pasta, 
            state="disabled"
        )
        self.btn_abrir.pack(side="right", fill="x", expand=True)

        # Botão para enviar as fotos selecionadas para o Google Drive
        self.btn_enviar_drive = ctk.CTkButton(
            self, 
            text="📤 Enviar Fotos Selecionadas para o Google Drive", 
            height=45, 
            font=ctk.CTkFont(size=14, weight="bold"), 
            fg_color="#4285F4", 
            hover_color="#357ae8", 
            command=self.iniciar_upload_drive, 
            state="disabled"
        )
        self.btn_enviar_drive.pack(pady=(5, 20), padx=40, fill="x")

    def monitorar_cartao(self):
        drives_iniciais = [p.device for p in psutil.disk_partitions()]
        while True:
            time.sleep(1.5)
            drives_atuais = [p.device for p in psutil.disk_partitions()]
            novos_drives = [d for d in drives_atuais if d not in drives_iniciais]
            if novos_drives:
                self.drive_path = novos_drives[0]
                self.cartao_detectado = True
                self.origem_manual = False
                self.atualizar_ui_cartao_detectado(self.drive_path)
                drives_iniciais = drives_atuais
            elif len(drives_atuais) < len(drives_iniciais):
                # Se o usuário escolheu uma origem manual, ignoramos a remoção de outros drives
                if self.origem_manual:
                    drives_iniciais = drives_atuais
                else:
                    self.drive_path = ""
                    self.cartao_detectado = False
                    self.atualizar_ui_cartao_removido()
                    drives_iniciais = drives_atuais

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
            
            # Opção de importar a pasta raiz inteira de forma direta
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
        self.lbl_vazio.pack(pady=40)

    def selecionar_destino(self):
        pasta = filedialog.askdirectory(title="Selecione onde salvar as fotos")
        if pasta:
            self.destino_path.set(pasta)

    def iniciar_transferencia(self):
        if not self.cartao_detectado:
            messagebox.showwarning("Aviso", "Nenhum cartão SD detectado!")
            return
            
        nome_fotografo = self.entry_nome.get().strip()
        if not nome_fotografo:
            messagebox.showwarning("Aviso", "Por favor, digite o nome do fotógrafo!")
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
        
        converter = self.converter_raw_var.get()
        
        # Limpa os arquivos transferidos antes de uma nova importação
        self.arquivos_transferidos.clear()
        
        thread_copia = threading.Thread(target=self.processar_copia, args=(nome_fotografo, destino, pastas_selecionadas, converter))
        thread_copia.start()

    def processar_copia(self, nome_fotografo, destino, pastas_selecionadas, converter_raw):
        arquivos_para_copiar = []
        
        for pasta_relativa in pastas_selecionadas:
            pasta_origem = os.path.join(self.drive_path, os.path.normpath(pasta_relativa))
            if os.path.exists(pasta_origem):
                for root, dirs, files in os.walk(pasta_origem):
                    for file in files:
                        if file.lower().endswith(('.png', '.jpg', '.jpeg', '.cr2', '.nef', '.arw', '.mp4')):
                            arquivos_para_copiar.append(os.path.join(root, file))

        total_arquivos = len(arquivos_para_copiar)
        if total_arquivos == 0:
            self.after(0, lambda: messagebox.showinfo("Informação", "Nenhuma imagem encontrada nas pastas selecionadas."))
            self.after(0, lambda: self.btn_iniciar.configure(state="normal"))
            return

        progresso_atual = 0
        lock = threading.Lock()

        def processar_arquivo(caminho_arquivo):
            nonlocal progresso_atual
            nome_original = os.path.basename(caminho_arquivo)
            nome_sem_ext, ext = os.path.splitext(nome_original)
            eh_raw = ext.lower() in ['.cr2', '.nef', '.arw']
            
            if converter_raw and eh_raw:
                novo_nome = f"{nome_fotografo}_{nome_sem_ext}.jpg"
            else:
                novo_nome = f"{nome_fotografo}_{nome_original}"
                
            caminho_destino = os.path.join(destino, novo_nome)

            contador = 1
            while os.path.exists(caminho_destino):
                nome_base, ext_base = os.path.splitext(novo_nome)
                caminho_destino = os.path.join(destino, f"{nome_base}_{contador}{ext_base}")
                contador += 1

            try:
                if converter_raw and eh_raw:
                    # Revelação real em alta qualidade usando a CPU
                    with rawpy.imread(caminho_arquivo) as raw:
                        rgb = raw.postprocess(use_camera_wb=True)
                        imageio.imsave(caminho_destino, rgb)
                else:
                    # Cópia direta do arquivo
                    shutil.copy2(caminho_arquivo, caminho_destino)
                
                # Armazena os arquivos transferidos com sucesso de forma thread-safe
                with lock:
                    # Só adicionamos imagens legíveis (ignoramos vídeos no revisor se houver)
                    if caminho_destino.lower().endswith(('.png', '.jpg', '.jpeg', '.cr2', '.nef', '.arw')):
                        self.arquivos_transferidos.append(caminho_destino)
            except Exception as e:
                print(f"Erro ao processar {nome_original}: {e}")
            
            with lock:
                progresso_atual += 1
                progresso = progresso_atual / total_arquivos
                percentual = int(progresso * 100)
                self.progressbar.set(progresso)
                self.lbl_progresso.configure(text=f"Progresso: {percentual}% ({progresso_atual}/{total_arquivos})")

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            executor.map(processar_arquivo, arquivos_para_copiar)

        # Chama a finalização da transferência de forma segura na thread principal
        self.after(0, self.finalizar_transferencia_gui)

    def finalizar_transferencia_gui(self):
        self.btn_iniciar.configure(state="normal")
        self.btn_abrir.configure(state="normal")
        self.progressbar.set(0)
        self.lbl_progresso.configure(text="Progresso: 0%")
        
        total_fotos = len(self.arquivos_transferidos)
        if total_fotos > 0:
            self.btn_selecionar.configure(state="normal")
            
            # Garantimos que o botão do Drive comece desabilitado caso o usuário queira revisar as fotos primeiro
            self.btn_enviar_drive.configure(state="disabled")
            
            # Pergunta se o usuário gostaria de abrir o painel de seleção diretamente
            revisar = messagebox.askyesno(
                "Transferência Finalizada",
                f"Foram transferidas {total_fotos} foto(s) com sucesso!\n\n"
                "Deseja iniciar a tela de seleção agora para revisar e apagar as fotos indesejadas?"
            )
            if revisar:
                self.abrir_revisor()
            else:
                # Se ele escolheu NÃO revisar, pode subir tudo imediatamente
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
        self.btn_enviar_drive.configure(state="disabled") # Desabilita o Drive durante a revisão
        
        # Abre a tela de revisão
        self.janela_revisao = RevisorFotosWindow(self, self.arquivos_transferidos, self.destino_path.get())

    def abrir_pasta(self):
        destino = self.destino_path.get()
        if destino and os.path.exists(destino):
            if platform.system() == "Windows":
                os.startfile(destino)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", destino])
            else:
                subprocess.Popen(["xdg-open", destino])

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

        nome_fotografo = self.entry_nome.get().strip()
        if not nome_fotografo:
            messagebox.showwarning("Aviso", "Por favor, preencha o nome do fotógrafo para organizar a pasta no Google Drive!")
            return

        caminho_credenciais = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")
        if not os.path.exists(caminho_credenciais):
            messagebox.showerror(
                "Credenciais Não Encontradas", 
                "O arquivo 'credentials.json' não foi encontrado na pasta do aplicativo!\n\n"
                "Por favor, siga o guia 'google_drive_credentials_guide.md' para gerar "
                "suas credenciais e salve o arquivo como 'credentials.json' na pasta do programa."
            )
            return

        # Desabilita botões para evitar ações concorrentes durante o upload
        self.btn_iniciar.configure(state="disabled")
        self.btn_selecionar.configure(state="disabled")
        self.btn_abrir.configure(state="disabled")
        self.btn_enviar_drive.configure(state="disabled")
        self.btn_manual.configure(state="disabled")

        # Inicia a thread de upload em segundo plano para não travar a UI
        thread_upload = threading.Thread(
            target=self.processar_upload_drive, 
            args=(nome_fotografo, caminho_credenciais), 
            daemon=True
        )
        thread_upload.start()

    def processar_upload_drive(self, nome_fotografo, caminho_credenciais):
        SCOPES = ['https://www.googleapis.com/auth/drive']
        token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'token.json')
        creds = None
        
        # Carrega o token.json se existir e for válido
        if os.path.exists(token_path):
            try:
                creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            except Exception as e:
                print(f"Erro ao carregar token.json: {e}")
                creds = None

        # Se não houver credenciais válidas, realiza o login
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    self.after(0, lambda: self.lbl_progresso.configure(text="Atualizando acesso com o Google..."))
                    creds.refresh(Request())
                except Exception:
                    creds = None
            
            if not creds:
                # UX: Avisa o usuário que abrirá o navegador antes que a janela surja
                self.after(0, lambda: messagebox.showinfo(
                    "Autenticação do Google", 
                    "Uma janela do seu navegador de internet será aberta para que você faça login com sua conta do Google "
                    "e conceda acesso para o aplicativo enviar as fotos.\n\n"
                    "Por favor, confirme a autorização no seu navegador."
                ))
                try:
                    self.after(0, lambda: self.lbl_progresso.configure(text="Aguardando autorização no navegador..."))
                    flow = InstalledAppFlow.from_client_secrets_file(caminho_credenciais, SCOPES)
                    creds = flow.run_local_server(port=0)
                    
                    # Salva as credenciais para evitar logins futuros
                    with open(token_path, 'w') as token_file:
                        token_file.write(creds.to_json())
                except Exception as e:
                    self.after(0, lambda: messagebox.showerror("Erro de Autenticação", f"Não foi possível autenticar: {e}"))
                    self.after(0, self.finalizar_upload_gui)
                    return

        try:
            self.after(0, lambda: self.lbl_progresso.configure(text="Conectando ao Google Drive..."))
            service = build('drive', 'v3', credentials=creds)

            # Define o nome para a pasta organizada
            nome_pasta_drive = f"Fotos - {nome_fotografo} - {time.strftime('%d-%m-%Y')}"
            self.after(0, lambda: self.lbl_progresso.configure(text=f"Criando pasta '{nome_pasta_drive}' no Drive..."))
            
            folder_metadata = {
                'name': nome_pasta_drive,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            folder = service.files().create(body=folder_metadata, fields='id').execute()
            folder_id = folder.get('id')

            arquivos_para_enviar = self.arquivos_transferidos.copy()
            total_arquivos = len(arquivos_para_enviar)
            progresso_atual = 0

            for caminho_arquivo in arquivos_para_enviar:
                if not os.path.exists(caminho_arquivo):
                    progresso_atual += 1
                    continue
                
                nome_arquivo = os.path.basename(caminho_arquivo)
                self.after(0, lambda n=nome_arquivo, p=progresso_atual+1, t=total_arquivos: self.lbl_progresso.configure(
                    text=f"Enviando ({p}/{t}): {n}"
                ))
                
                file_metadata = {
                    'name': nome_arquivo,
                    'parents': [folder_id]
                }
                
                # Determina o MIME type com base na extensão
                ext = os.path.splitext(nome_arquivo)[1].lower()
                if ext in ['.jpg', '.jpeg']:
                    mime = 'image/jpeg'
                elif ext == '.png':
                    mime = 'image/png'
                elif ext in ['.cr2', '.nef', '.arw']:
                    mime = 'image/x-raw'
                elif ext == '.mp4':
                    mime = 'video/mp4'
                else:
                    mime = 'application/octet-stream'

                try:
                    # Envio com MediaFileUpload resumable para suportar fotos pesadas e acompanhar progresso fino
                    media = MediaFileUpload(caminho_arquivo, mimetype=mime, resumable=True)
                    request = service.files().create(body=file_metadata, media_body=media, fields='id')
                    
                    response = None
                    while response is None:
                        status, response = request.next_chunk()
                        if status:
                            percentual_arquivo = int(status.progress() * 100)
                            self.after(0, lambda n=nome_arquivo, p=progresso_atual+1, t=total_arquivos, pct=percentual_arquivo: 
                                self.lbl_progresso.configure(text=f"Enviando ({p}/{t}): {n} ({pct}%)")
                            )
                            # Atualiza a barra de progresso do CustomTkinter dinamicamente
                            progresso_frac = (progresso_atual + status.progress()) / total_arquivos
                            self.after(0, lambda pf=progresso_frac: self.progressbar.set(pf))
                except Exception as e:
                    print(f"Erro ao enviar arquivo {nome_arquivo}: {e}")

                progresso_atual += 1
                progresso_geral = progresso_atual / total_arquivos
                self.after(0, lambda pg=progresso_geral: self.progressbar.set(pg))

            self.after(0, lambda: messagebox.showinfo(
                "Upload Concluído", 
                f"Sucesso! {total_arquivos} fotos foram enviadas com sucesso para a pasta '{nome_pasta_drive}' no seu Google Drive!"
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
        self.progressbar.set(0)
        self.lbl_progresso.configure(text="Progresso: 0%")

if __name__ == "__main__":
    app = ImportadorFotosApp()
    app.mainloop()