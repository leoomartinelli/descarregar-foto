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

# Configurações de tema do CustomTkinter
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class ImportadorFotosApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Descarregador de Fotos - Ministério")
        self.geometry("600x720")
        self.resizable(False, False)

        self.destino_path = ctk.StringVar()
        self.cartao_detectado = False
        self.drive_path = ""
        self.checkboxes_pastas = []
        
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

        self.lbl_pastas = ctk.CTkLabel(self, text="Pastas no Cartão SD:")
        self.lbl_pastas.pack(anchor="w", padx=40)
        
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

        self.frame_botoes = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_botoes.pack(pady=(10, 20), padx=40, fill="x")

        self.btn_iniciar = ctk.CTkButton(self.frame_botoes, text="Iniciar Transferência", font=ctk.CTkFont(size=15, weight="bold"), height=45, fg_color="green", hover_color="darkgreen", command=self.iniciar_transferencia)
        self.btn_iniciar.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.btn_abrir = ctk.CTkButton(self.frame_botoes, text="Abrir Pasta", height=45, font=ctk.CTkFont(size=14), command=self.abrir_pasta, state="disabled")
        self.btn_abrir.pack(side="right", fill="x", expand=True)

    def monitorar_cartao(self):
        drives_iniciais = [p.device for p in psutil.disk_partitions()]
        while True:
            time.sleep(1.5)
            drives_atuais = [p.device for p in psutil.disk_partitions()]
            novos_drives = [d for d in drives_atuais if d not in drives_iniciais]
            if novos_drives:
                self.drive_path = novos_drives[0]
                self.cartao_detectado = True
                self.atualizar_ui_cartao_detectado(self.drive_path)
                drives_iniciais = drives_atuais
            elif len(drives_atuais) < len(drives_iniciais):
                self.drive_path = ""
                self.cartao_detectado = False
                self.atualizar_ui_cartao_removido()
                drives_iniciais = drives_atuais

    def atualizar_ui_cartao_detectado(self, drive):
        self.lbl_status.configure(text=f"Cartão Detectado: {drive}", text_color="lightgreen")
        for widget in self.frame_pastas.winfo_children():
            widget.destroy()
        self.checkboxes_pastas.clear()
        
        try:
            pastas_encontradas = []
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
                
            if not pastas_encontradas:
                lbl = ctk.CTkLabel(self.frame_pastas, text="Nenhuma pasta de fotos encontrada no cartão.")
                lbl.pack(pady=20)
                
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
        self.btn_abrir.configure(state="disabled")
        
        converter = self.converter_raw_var.get()
        
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
            messagebox.showinfo("Informação", "Nenhuma imagem encontrada nas pastas selecionadas.")
            self.btn_iniciar.configure(state="normal")
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
            except Exception as e:
                print(f"Erro ao processar {nome_original}: {e}")
            
            # Atualiza a interface de forma segura entre as threads
            with lock:
                progresso_atual += 1
                progresso = progresso_atual / total_arquivos
                percentual = int(progresso * 100)
                self.progressbar.set(progresso)
                self.lbl_progresso.configure(text=f"Progresso: {percentual}% ({progresso_atual}/{total_arquivos})")

        # Roda o processamento dividindo a carga entre 4 núcleos simultaneamente
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            executor.map(processar_arquivo, arquivos_para_copiar)

        messagebox.showinfo("Sucesso", "Transferência finalizada!")
        self.btn_iniciar.configure(state="normal")
        self.btn_abrir.configure(state="normal")
        self.progressbar.set(0)
        self.lbl_progresso.configure(text="Progresso: 0%")

    def abrir_pasta(self):
        destino = self.destino_path.get()
        if destino and os.path.exists(destino):
            if platform.system() == "Windows":
                os.startfile(destino)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", destino])
            else:
                subprocess.Popen(["xdg-open", destino])

if __name__ == "__main__":
    app = ImportadorFotosApp()
    app.mainloop()